// arb-obs PM2 app entry. Kept as a standalone file, NOT merged into
// /root/rsibot/ecosystem.config.js, per the spec's zero-coupling requirement.
// Task 2 (blocked) runs this with: pm2 start ecosystem.snippet.js
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
      },
    },
  ],
};
