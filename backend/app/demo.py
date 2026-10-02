"""The demo assistant on the landing page answers questions about Greetwell itself."""

DEMO_BOT_ID = "demo"

DEMO_TEXT = """Greetwell
Greetwell turns a small business's website into an AI assistant that answers visitors and qualifies leads.

## What it does
A business owner pastes their website address. Greetwell reads the site (the home page and up to seven of the most useful linked pages, such as pricing, services, about and FAQ) and in about a minute produces a chat assistant that knows the business. The owner copies one line of code onto their site and the assistant appears as a chat bubble in the corner.
The assistant answers visitor questions using only what the business's own website says. When a visitor shows real interest, it asks what they need and how to reach them, and saves them as a lead. Each lead gets a score from 0 to 100 and a hot, warm or cold label, with the reasons shown, so the owner knows who to call first.

## Who it is for
Small and local businesses that get website visitors but lose them because nobody is there to answer: clinics, agencies, contractors, salons, schools, consultants, SaaS startups and online shops. It is built for owners who do not have a developer or a sales team.

## How to get started
- Go to the Greetwell home page and paste your website address.
- Wait about a minute while it reads your site.
- Try the assistant in the preview, adjust the greeting, colour and qualifying questions in the dashboard.
- Copy the one-line embed code into your website, just before the closing body tag. It works on WordPress, Shopify, Wix, Squarespace, Webflow and plain HTML sites.
No account or signup is needed. You get a private dashboard link; keep it safe because it is the key to your dashboard.
If you do not have a website, you can describe your business in a text box instead.

## Dashboard
- Leads: every captured lead with name, contact details, what they need, budget, timeline, score and the full conversation. Mark leads as contacted, qualified, won or lost. Export to CSV.
- Conversations: every chat, including ones that did not become leads, so you can see what visitors ask.
- Knowledge: the pages the assistant learned from, the business profile it wrote, and a notes box for facts that are not on your site, such as current promotions or holiday hours.
- Settings: assistant name, greeting, colour, starter questions, qualifying questions, and a webhook.

## Integrations
Greetwell can send each new lead to a webhook address as JSON the moment it is captured. This works with Slack incoming webhooks, Zapier, Make and n8n, so leads can go to a CRM, a spreadsheet or a team channel.

## Pricing
Greetwell is free while it is in beta. During the beta each assistant can handle up to 300 visitor messages per day. Paid plans for higher volume and multiple team members are planned; there is no price list yet.

## Accuracy and safety
The assistant is instructed to answer only from the business's own content and to say when it does not know, then offer to pass the question to the team. It never invents prices or promises. It always tells visitors it is an AI assistant if asked.

## Privacy and data
Conversations are stored for 45 days and then deleted automatically. Leads are kept until the owner deletes them. An owner can delete their assistant and all of its data from the dashboard at any time. Greetwell reads only public pages, identifies itself when it reads a site, and respects robots.txt.

## Languages
The assistant replies in the language the visitor writes in, and writes its greeting in the language of the business's website.

## Technology
Greetwell runs entirely on AWS: CloudFront and S3 serve the site and the widget, API Gateway and Lambda run the API, DynamoDB stores assistants, conversations and leads, and Claude on Amazon Bedrock powers the conversations. It was built and deployed with an AI coding agent for the AWS Zero to Shipped hackathon.

## Contact
For questions, partnerships or feedback, leave your email with the assistant and the Greetwell team will reply.
"""
