# Deployment files

## 3proxy systemd service (host installation)

For bare-metal / VM setups where 3proxy runs outside Docker:

```bash
sudo cp deployment/3proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable 3proxy
sudo systemctl start 3proxy
```

Make sure `/usr/local/bin/3proxy` is installed and `/etc/3proxy/3proxy.cfg` exists before starting the service.
