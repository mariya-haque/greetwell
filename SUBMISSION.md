<!--
  Draft of the Builder Center project page. Before posting:
  1. Run .\deploy.ps1 and replace every LIVE_URL below with the address it prints.
  2. Replace the two lines marked YOUR WORDS with your own.
  3. Add the screenshots listed at the bottom.
  4. Add both tags on the project: #commercial-potential and #startups.
-->

# Greetwell: paste your website address, get an AI assistant that qualifies your leads

**Category:** #commercial-potential  **Lane:** #startups
**Live app:** LIVE_URL
**Built with:** Claude Code (coding agent) connected to AWS through the AWS CLI. Runs on CloudFront, S3, API Gateway, Lambda, DynamoDB and Amazon Bedrock.

## The problem

A small business pays for every visitor that reaches its website, and then nobody is there to answer them. The visitor has one question (do you do this, what does it cost, can you come Thursday), doesn't find it in ten seconds, and leaves. Contact forms collect a fraction of them, and what they collect arrives unsorted: the owner can't tell the person ready to book from the student doing research.

Chat tools exist, but they expect someone to write scripts, maintain an FAQ, or sit at the keyboard. The owners who most need the help have neither a developer nor a sales team.

> YOUR WORDS: one or two sentences on why this problem is yours. For example, a client or a business you know that lost leads this way.

## What I built

Greetwell turns a website address into a working sales assistant in about a minute.

1. **Paste your address.** Greetwell reads the home page and the pages that matter most (pricing, services, about, FAQ, contact) and writes a profile of the business, including the questions worth asking its leads.
2. **Try it and tune it.** Chat with the assistant on a preview page. Change its name, greeting, colour and qualifying questions. Add notes for anything the site doesn't say.
3. **Add one line of code.** A single script tag puts the assistant on any site: WordPress, Shopify, Wix, Squarespace, Webflow or plain HTML.

From then on the assistant answers visitors using only the business's own content, admits when it doesn't know, and replies in the visitor's language. When a visitor shows real interest it learns what they need and how to reach them. The owner's dashboard shows every lead with a score from 0 to 100, a hot, warm or cold label, the reasons for that score and the full conversation. New leads can go straight to Slack, Zapier or a CRM through a webhook.

There is no signup. You get a private dashboard link and you are done.

**Try it now:** open LIVE_URL. The chat bubble on that page is a live Greetwell assistant that knows about Greetwell, so you can test it without building anything. To see the whole product, paste any small business's website address and follow the dashboard link.

## How it works on AWS

| Layer | Service | What it does here |
|---|---|---|
| Delivery | CloudFront + S3 | Serves the site and the embeddable widget worldwide, and fronts the API on the same domain |
| API | API Gateway + Lambda | One Python function for assistants, chat and leads |
| Site reader | Lambda (async) | Reads the site in the background so the first click returns instantly |
| Data | DynamoDB | One table for assistants, conversations, leads and rate-limit counters |
| Knowledge | S3 | One knowledge base document per assistant |
| Intelligence | Claude on Amazon Bedrock | Writes the business profile and holds the conversations |

The whole stack is one CloudFormation template and nothing runs when nobody is chatting, so an assistant for a small business costs cents to operate.

Three decisions I'm proud of:

- **No vector database.** Small-business sites are small. Most knowledge bases fit in the prompt whole, behind a prompt-cache breakpoint, which is the most accurate option and the cheapest after the first message. Only large sites are narrowed per question, with BM25 computed inside the Lambda.
- **The model proposes, the server decides.** Claude reports what the visitor said through a tool call. The server validates the contact details, refuses a "lead" with no way to reach the person, and computes the score itself, so every score is explainable and can't be talked up.
- **A public app with a hard budget.** Anyone can use it without logging in, so every path to the model is capped per visitor, per conversation, per assistant and globally per day with atomic DynamoDB counters. The site reader resolves hostnames itself and connects only to public addresses it has checked, which blocks requests aimed at internal services.

## How the coding agent helped me ship

I built Greetwell with Claude Code running in VS Code, and gave it the AWS CLI so it could work against my account directly.

- **Scoping.** I gave the agent the hackathon brief. It proposed four app ideas sized for the deadline and I picked this one and the Startups lane.
- **Research before code.** It looked up the current way to call Claude on Bedrock and found two things that changed the design: newer models are reached through a different endpoint than older tutorials show, and that endpoint has no structured-output mode. So lead capture uses a plain tool call with server-side validation, and the app carries a model fallback chain in case an account can't use the default model.
- **Building.** It wrote the backend, the widget, the dashboard and the infrastructure template, plus an in-memory mode so the whole app runs on a laptop with no AWS account.
- **Testing its own work.** It wrote 21 automated tests, ran the site reader against real websites (about five seconds for eight pages), and took screenshots of every page in a headless browser to check the layout. That caught real bugs: page titles polluted by icon labels inside SVGs, a navigation filter that threw away the links the reader needed, and a preview page where the open chat window covered the instructions.
- **Shipping.** It wrote a deploy script that confirms the AWS sign-in, builds the Lambda package, deploys the stack, seeds the demo assistant and then probes the live URL end to end, including a real model reply, before reporting success.

My part was the decisions: which product, which lane, what the assistant should and shouldn't do, and reviewing what it built. The full log is in `BUILD_LOG.md`.

### Proof of connection

The deploy script records the agent's connection to my AWS account: the `aws sts get-caller-identity` result, the resources CloudFormation created, and the post-deploy checks against the live URL. See `docs/proof/aws-connection.txt` and the screenshots below.

## Where it's headed

Greetwell is free while it's in beta. The plan from here:

- **Accounts and teams**, replacing the private-link model, so an agency can manage assistants for its clients.
- **Paid plans by conversation volume.** The serverless design means cost tracks usage, so a plan can be priced well under what a missed lead costs a business.
- **Channels.** The same assistant on WhatsApp and Instagram, where many small businesses already talk to customers.
- **Learning loop.** Show owners the questions the assistant couldn't answer, so each one becomes a line in their notes or a fix to their site.

The first users I want are local service businesses and the small agencies that build their websites: one agency can put Greetwell on every site it maintains.

> YOUR WORDS: one sentence on who you'll show this to first.

## Images to attach

Generated by `scripts/capture_screenshots.py` against the live site, in `docs/screenshots/`:

1. `1-landing.png`: landing page with the address box.
2. `2-demo-assistant.png`: the live demo assistant answering a question about Greetwell.
3. `3-building.png`: the "Building your assistant" progress screen.
4. `5-preview-conversation.png`: a customer conversation that ends with a captured lead.
5. `6-leads.png` and `7-lead-detail.png`: the scored lead, the reasons for its score and the transcript.
6. `8-knowledge.png`: the pages and profile the assistant learned.
7. `docs/architecture.png`: the AWS architecture.
8. Proof of connection: a terminal screenshot of `aws sts get-caller-identity` and the deploy script's PASS lines, plus the CloudFormation console showing the `greetwell` stack.
