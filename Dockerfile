FROM ghcr.io/nightly-labs/openbot:latest
USER root
RUN sed -i 's|^exec /opt/OpenBot/app/openbot .*|exec /opt/OpenBot/app/openbot --password-store=gnome-libsecret ${OPENBOT_CHROMIUM_FLAGS:-} "${chromium[@]}"|' /opt/OpenBot/app/resources/hosting/openbot-container \
 && grep -q OPENBOT_CHROMIUM_FLAGS /opt/OpenBot/app/resources/hosting/openbot-container
ENV OPENBOT_CHROMIUM_FLAGS="--disable-features=WebRtcHideLocalIpsWithMdns"
USER 1000:1000
