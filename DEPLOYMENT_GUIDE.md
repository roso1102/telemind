# Deployment Guide for TeleMind Bot

This guide provides detailed instructions for deploying TeleMind Bot to various cloud platforms.

## Preparing for Deployment

Before deploying, make sure you have:

1. A Telegram bot token (from @BotFather)
2. A Groq API key (from groq.com)
3. A Firebase project with Firestore and Storage enabled
4. Your Firebase service account key file

## Option 1: Deploying to Render

[Render](https://render.com/) offers a free tier that's perfect for TeleMind Bot.

### Steps:

1. **Create a GitHub repository** with your TeleMind Bot code.

2. **Sign up for Render** and connect your GitHub account.

3. **Create a new Web Service**:
   - Select your repository
   - Choose "Python" as the Runtime
   - Set the Build Command: `pip install -r requirements.txt`
   - Set the Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. **Add Environment Variables**:
   - `GROQ_API_KEY`: Your Groq API key
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `WEBHOOK_URL`: Your Render service URL (https://your-app-name.onrender.com)

5. **Add Firebase Service Account**:
   - Go to the "Secret Files" section
   - Add your `firebase_service_account.json` file

6. **Deploy** and wait for the build to complete.

7. **Update your Telegram webhook**:
   - Visit: `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook`
   - Replace `{TELEGRAM_BOT_TOKEN}` with your token
   - Replace `{WEBHOOK_URL}` with your Render URL

## Option 2: Deploying to Fly.io

[Fly.io](https://fly.io/) offers a generous free tier with global distribution.

### Steps:

1. **Install the Fly CLI**:
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```

2. **Login to Fly.io**:
   ```bash
   fly auth login
   ```

3. **Create a Dockerfile** in your project root:
   ```Dockerfile
   FROM python:3.9-slim
   
   WORKDIR /app
   
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   
   COPY . .
   
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
   ```

4. **Create a fly.toml file**:
   ```toml
   app = "telemind-bot"  # Change to your preferred name
   
   [build]
   
   [http_service]
     internal_port = 8080
     force_https = true
   
   [env]
     PORT = "8080"
   ```

5. **Launch your app**:
   ```bash
   fly launch
   ```

6. **Set secrets**:
   ```bash
   fly secrets set GROQ_API_KEY="your_groq_api_key"
   fly secrets set TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
   fly secrets set WEBHOOK_URL="https://your-app.fly.dev"
   ```

7. **Upload Firebase service account**:
   ```bash
   fly secrets set FIREBASE_SERVICE_ACCOUNT="$(cat firebase_service_account.json)"
   ```
   Then modify your code to load the JSON from the environment variable.

8. **Deploy**:
   ```bash
   fly deploy
   ```

9. **Update Telegram webhook** as in the Render instructions.

## Option 3: Railway App

[Railway](https://railway.app/) offers a simple deployment experience with a free starter plan.

### Steps:

1. **Sign up for Railway** and connect your GitHub account.

2. **Create a new project** and select your GitHub repository.

3. **Add environment variables**:
   - `GROQ_API_KEY`: Your Groq API key
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `WEBHOOK_URL`: Your Railway app URL

4. **Add Firebase Service Account**:
   - Either add as a secret file or as an environment variable

5. **Configure start command**:
   - Add a `Procfile` to your repository with:
     ```
     web: uvicorn main:app --host 0.0.0.0 --port $PORT
     ```

6. **Deploy** and wait for the build to complete.

7. **Update Telegram webhook** as described earlier.

## Managing Firebase in Production

For production environments, consider these Firebase best practices:

1. **Set appropriate security rules** for Firestore and Storage.

2. **Use Firebase Authentication** if you want to add multi-user support.

3. **Set up Firebase backup** to prevent data loss.

4. **Monitor usage** to stay within free tier limits.

## Troubleshooting

### Webhook Issues
- Verify your webhook URL is correct and accessible
- Check that the `/webhook` endpoint is correctly implemented
- Ensure the Telegram Bot API token is valid

### Firebase Issues
- Verify your service account has proper permissions
- Check that Firestore and Storage are enabled in your Firebase project
- Ensure your service account key is correctly loaded

### Bot Not Responding
- Check application logs in your hosting platform
- Verify environment variables are correctly set
- Ensure the bot is still registered with BotFather
