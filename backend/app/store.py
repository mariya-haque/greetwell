"""Storage behind one small interface.

Everything lives in a single table keyed by (pk, sk), plus a blob store for
knowledge bases that can outgrow a DynamoDB item:

    BOT#<id>   META            the bot and its settings
    BOT#<id>   SESS#<session>  one visitor conversation
    BOT#<id>   LEAD#<session>  the lead captured in that conversation
    RATE#<key> <day>           a rate-limit counter

`MemoryStore` implements the same interface in a dict for local development
and tests.
"""
import copy
import json
import threading

from . import config
from .util import plain


class MemoryStore:
    def __init__(self):
        self._items = {}
        self._blobs = {}
        self._lock = threading.Lock()

    def get(self, pk, sk):
        with self._lock:
            return copy.deepcopy(self._items.get((pk, sk)))

    def put(self, item):
        with self._lock:
            self._items[(item["pk"], item["sk"])] = copy.deepcopy(item)

    def update(self, pk, sk, sets=None, adds=None):
        with self._lock:
            item = self._items.get((pk, sk))
            if item is None:
                return None
            for name, value in (sets or {}).items():
                item[name] = copy.deepcopy(value)
            for name, amount in (adds or {}).items():
                item[name] = item.get(name, 0) + amount
            return copy.deepcopy(item)

    def query(self, pk, prefix="", limit=500):
        with self._lock:
            rows = [
                copy.deepcopy(v)
                for (p, s), v in sorted(self._items.items())
                if p == pk and s.startswith(prefix)
            ]
        return rows[:limit]

    def delete(self, pk, sk):
        with self._lock:
            self._items.pop((pk, sk), None)

    def delete_partition(self, pk):
        with self._lock:
            for key in [k for k in self._items if k[0] == pk]:
                del self._items[key]

    def bump(self, pk, sk, limit, ttl):
        """Count one event. False once `limit` events were already counted."""
        with self._lock:
            item = self._items.setdefault((pk, sk), {"pk": pk, "sk": sk, "n": 0})
            if item["n"] >= limit:
                return False
            item["n"] += 1
            item["ttl"] = ttl
            return True

    def blob_put(self, key, obj):
        with self._lock:
            self._blobs[key] = json.dumps(obj)

    def blob_get(self, key):
        with self._lock:
            raw = self._blobs.get(key)
        return json.loads(raw) if raw is not None else None

    def blob_delete(self, key):
        with self._lock:
            self._blobs.pop(key, None)


class AwsStore:
    def __init__(self, table_name=None, bucket=None):
        import boto3
        from boto3.dynamodb.conditions import Key
        from botocore.exceptions import ClientError

        self._Key = Key
        self._ClientError = ClientError
        self._table = boto3.resource("dynamodb").Table(table_name or config.TABLE_NAME)
        self._s3 = boto3.client("s3")
        self._bucket = bucket or config.DATA_BUCKET

    def _conditional_failed(self, err):
        return err.response["Error"]["Code"] == "ConditionalCheckFailedException"

    def get(self, pk, sk):
        item = self._table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return plain(item) if item else None

    def put(self, item):
        self._table.put_item(Item=item)

    def update(self, pk, sk, sets=None, adds=None):
        names, values, clauses = {}, {}, []
        if sets:
            parts = []
            for i, (name, value) in enumerate(sets.items()):
                names[f"#s{i}"], values[f":s{i}"] = name, value
                parts.append(f"#s{i} = :s{i}")
            clauses.append("SET " + ", ".join(parts))
        if adds:
            parts = []
            for i, (name, amount) in enumerate(adds.items()):
                names[f"#a{i}"], values[f":a{i}"] = name, amount
                parts.append(f"#a{i} :a{i}")
            clauses.append("ADD " + ", ".join(parts))
        if not clauses:
            return self.get(pk, sk)
        try:
            result = self._table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression=" ".join(clauses),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression="attribute_exists(pk)",
                ReturnValues="ALL_NEW",
            )
        except self._ClientError as err:
            if self._conditional_failed(err):
                return None
            raise
        return plain(result["Attributes"])

    def query(self, pk, prefix="", limit=500):
        condition = self._Key("pk").eq(pk)
        if prefix:
            condition = condition & self._Key("sk").begins_with(prefix)
        rows, kwargs = [], {"KeyConditionExpression": condition}
        while len(rows) < limit:
            page = self._table.query(**kwargs)
            rows.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return plain(rows[:limit])

    def delete(self, pk, sk):
        self._table.delete_item(Key={"pk": pk, "sk": sk})

    def delete_partition(self, pk):
        kwargs = {
            "KeyConditionExpression": self._Key("pk").eq(pk),
            "ProjectionExpression": "pk, sk",
        }
        with self._table.batch_writer() as batch:
            while True:
                page = self._table.query(**kwargs)
                for row in page.get("Items", []):
                    batch.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def bump(self, pk, sk, limit, ttl):
        try:
            self._table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="ADD #n :one SET #t = :ttl",
                ConditionExpression="attribute_not_exists(#n) OR #n < :limit",
                ExpressionAttributeNames={"#n": "n", "#t": "ttl"},
                ExpressionAttributeValues={":one": 1, ":limit": limit, ":ttl": ttl},
            )
        except self._ClientError as err:
            if self._conditional_failed(err):
                return False
            raise
        return True

    def blob_put(self, key, obj):
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(obj).encode("utf-8"),
            ContentType="application/json",
        )

    def blob_get(self, key):
        try:
            body = self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except self._ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        return json.loads(body)

    def blob_delete(self, key):
        self._s3.delete_object(Bucket=self._bucket, Key=key)
