FROM ghcr.io/nightly-labs/openbot:latest

USER root

ENV HOME=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY login_bridge.py /opt/openbot-login-bridge.py

RUN chmod 755 /opt/openbot-login-bridge.py \
    && sed -i '/^unshare --user --map-root-user true 2>\/dev\/null ||$/,+1d' \
       /opt/OpenBot/app/resources/hosting/openbot-container \
    && sed -i 's/openbot --password-store=gnome-libsecret/openbot --no-sandbox --password-store=gnome-libsecret/' \
       /opt/OpenBot/app/resources/hosting/openbot-container \
    && sed -i '/^export OPENBOT_SERVER=1$/i python3 /opt/openbot-login-bridge.py >/tmp/openbot-login-bridge.log 2>\&1 &' \
       /opt/OpenBot/app/resources/hosting/openbot-container

EXPOSE 7860

USER 1000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/OpenBot/app/resources/hosting/openbot-container"]
