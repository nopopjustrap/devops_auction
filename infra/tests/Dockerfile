FROM debian:12-slim
ENV DEBIAN_FRONTEND=noninteractive container=docker
RUN apt-get update && apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /root/.ssh /run/sshd \
    && chmod 700 /root/.ssh \
    && passwd -d root \
    && printf 'PermitRootLogin prohibit-password\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/10-initial.conf \
    && rm -f /etc/ssh/ssh_host_* \
    && systemctl enable ssh
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
