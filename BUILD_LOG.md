# Build log

How Greetwell was built with a coding agent (Claude Code, model Claude Opus 5.5, running in VS Code on Windows 11). Kept as the development-process record for the Zero to Shipped submission. Entries are in the order things happened.

## Day 1: 30 September 2026

**Starting point.** An empty folder and the hackathon brief. The machine had Python 3.13, Git and Docker, and no AWS CLI, Node.js or AWS credentials.

**Choosing what to build.** The agent proposed four ideas sized for a two-day build on serverless AWS (a heat-risk advisor, a lead-qualifier bot builder, a standup digest board, a picture-book maker). The builder chose the lead-qualifier bot builder in the Startups lane, and chose to configure AWS credentials personally rather than pass keys through the chat.

**Tooling.** The agent installed AWS CLI v2 with winget.

**Research that changed the design.** Before writing code the agent checked the current documentation for Claude on Amazon Bedrock and found:

- Current Claude models are served from Bedrock's Messages-API endpoint through the Anthropic SDK's `AnthropicBedrockMantle` client, with IDs such as `anthropic.claude-opus-5-5`, rather than the older Converse API that most tutorials use.
- That endpoint has no structured-output mode, and the newest models reject a forced tool choice. So both lead capture and profile extraction use an ordinary tool call, the prompt asks for it, and the server validates what comes back.
- Access to the newest models varies by account, while Claude Opus 4.8 and Haiku 4.5 are open to every Bedrock customer. The app therefore carries a fallback chain and switches at run time if the default model is unavailable, so a model-access surprise cannot fail the ship gate.
- The IAM action for that endpoint is `bedrock-mantle:CreateInference`.

**Architecture decisions.**

- Python on Lambda with no build step for the frontend (plain HTML, CSS and JavaScript), because the machine had no Node.js and fewer moving parts means fewer ways to miss a deadline.
- One CloudFront distribution in front of both the S3 site and the API, so the dashboard has no cross-origin calls and the API can refuse anything that didn't come through CloudFront.
- A background Lambda for reading sites. API Gateway allows 30 seconds per request and reading a site plus writing a profile can take longer.
- No login. A public demo has to be usable by judges and by an automated scorer in one click. Ownership is a secret in the dashboard link's URL fragment, stored hashed.
- No vector database. Knowledge bases under 30k characters go into the prompt whole and are cached; larger ones use BM25 inside the Lambda.
- Storage and the model sit behind small interfaces with in-memory implementations, so the whole app runs and is tested locally with no AWS account.

**Backend written.** Guarded fetcher and crawler, HTML-to-text extraction, knowledge chunking and retrieval, model client, chat orchestration with the `save_lead` tool, lead scoring, rate limits, API router, background builder.

**Tests.** 21 tests using only the standard library, including an end-to-end run against a small website served locally: create an assistant, chat, capture a lead, read it back through the dashboard API, check that owner endpoints reject a wrong key, and check that settings survive a re-read of the site.

Problems the tests and real-site runs caught:

- The port allow-list rejected the test server. The check is now relaxed only when the private-address test switch is on.
- Stripe's pricing page came back titled "Pricing & FeesStripe logoStripe logo…": inline SVG icons contain their own `<title>` elements. The extractor now takes only the document's first title outside skipped regions.
- Dropping `<nav>` from page text also dropped the navigation links, which are the best map of a site. Links are now collected even inside skipped regions.
- Email addresses found in running text were sometimes examples from the page. `mailto:` links are now trusted first.
- A failed re-read of a site would have marked a working assistant as failed. A refresh failure now leaves the assistant serving what it learned before and shows the error in the dashboard.

Real-site crawl timings from this machine: python.org 7 pages in 4.0 s, stripe.com 8 pages in 5.4 s, basecamp.com 8 pages in 5.0 s.

**Frontend written.** Landing page, embeddable widget (shadow DOM, keyboard accessible, mobile full-screen), dashboard with five tabs, preview page.

**Visual checks.** The agent ran the app locally, built an assistant from a real site, and captured every page with headless Chrome at desktop and phone widths. Fixes from looking at the screenshots: header and hero gutters were 24 px off from the rest of the page, and on the preview page the open chat window covered the instructions card.

**Driving the real interface.** Screenshots don't prove that clicking works, so the agent scripted headless Chrome over the DevTools protocol to use the app the way a person would: submit the landing form, wait for the build, open the preview, tap a starter question, send a message containing an email address and an `<img onerror>` injection attempt, reload to confirm the conversation is restored, open the lead in the dashboard, change its status, and change the assistant's name and colour. Result: every step passed, the injected markup rendered as inert text in both the widget and the dashboard, and the browser reported no JavaScript errors.

**Infrastructure written.** A CloudFormation (SAM) template and `deploy.ps1`. The template passes `cfn-lint`. The Lambda packaging step was run for real on this machine: Linux wheels install correctly from Windows and the package is 19 MB.

**Cost guard added.** Default daily caps were lowered and an optional AWS Budget alert was added, because the default model is the most capable one and the endpoint is public.

**State at the end of this entry.** Everything that can be verified without an AWS account is built and verified. Not yet done: the deployment itself, which is waiting on AWS credentials being configured on this machine. Nothing AWS-side has been exercised yet, so the Bedrock call path, the IAM policy and the CloudFront routing are untested until the first deploy.

<!-- Add the deployment entry here after running deploy.ps1: date, the PASS lines it printed, anything that needed fixing. -->
