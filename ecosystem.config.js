// arb-obs PM2 app entry. Kept as a standalone file, NOT merged into
// /root/rsibot/ecosystem.config.js, per the spec's zero-coupling requirement.
module.exports = {
  apps: [
    {
      name: "arb-obs",
      script: "./arb_env/bin/python3",
      args: "data_logger.py",
      cwd: "/root/arb",
      max_memory_restart: "256M",
      autorestart: true,
      env: {
        PYTHONUNBUFFERED: "1",
        KALSHI_API_KEY_ID: "10c3df74-cc88-4ed4-9e4a-bc3a8dafabdf",
        KALSHI_PRIVATE_KEY_PATH: "/root/arb-secrets/kalshi_key.txt",
        KALSHI_REST_BASE: "https://external-api.kalshi.com/trade-api/v2",
      },
    },
  ],
};
