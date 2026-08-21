# YouTube Data API key setup

1. Enable YouTube Data API v3:
   <https://console.cloud.google.com/apis/library/youtube.googleapis.com>
2. Create an API key:
   <https://console.cloud.google.com/apis/credentials>
3. Restrict the key to YouTube Data API v3.
4. Set `YOUTUBE_API_KEY` in the environment or in a workspace-local `.env` that
   is excluded from Git.
5. Never paste the key into chat, logs, reports, or GitHub.

Reading public top-level comments uses the API key and does not require channel
login or OAuth.
