#!/bin/bash
# Cheapest host: a Lightsail nano (512 MB, 2 vCPU, 20 GB SSD, public IPv4 included) with a free static IP,
# ports 22/80/443 open, then bootstrap.sh over SSH. Idempotent: re-run to redeploy.
# Uses the AWS CLI's current credentials, e.g.:
#
#   AWS_PROFILE=personal AWS_DEFAULT_REGION=ap-south-1 ./deploy/provision_lightsail.sh
#
# Optional: NAME (claude-blooded), BUNDLE (nano_3_1), BLUEPRINT (amazon_linux_2023), ZONE (<region>a),
#           KEY_NAME (claude-blooded), REPO (git URL)
set -euo pipefail
REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
NAME="${NAME:-claude-blooded}"
BUNDLE="${BUNDLE:-nano_3_1}"
BLUEPRINT="${BLUEPRINT:-amazon_linux_2023}"
ZONE="${ZONE:-${REGION}a}"
KEY_NAME="${KEY_NAME:-claude-blooded}"
KEY_FILE="$HOME/.ssh/$KEY_NAME.pem"
REPO="${REPO:-https://github.com/cosmos-dx/claude-blooded.git}"
IP_NAME="$NAME-ip"
lsail() { aws lightsail --region "$REGION" "$@"; }

# SSH key: Lightsail stores only the public half; the private key stays in ~/.ssh
if [ ! -f "$KEY_FILE" ]; then mkdir -p "$HOME/.ssh"; ssh-keygen -q -t ed25519 -N "" -C "$KEY_NAME" -f "$KEY_FILE"; fi
if ! lsail get-key-pair --key-pair-name "$KEY_NAME" >/dev/null 2>&1; then
  lsail import-key-pair --key-pair-name "$KEY_NAME" --public-key-base64 "$(ssh-keygen -y -f "$KEY_FILE")" >/dev/null
  echo "imported key pair $KEY_NAME ($KEY_FILE)"
fi

if ! lsail get-instance --instance-name "$NAME" >/dev/null 2>&1; then
  lsail create-instances --instance-names "$NAME" --availability-zone "$ZONE" --blueprint-id "$BLUEPRINT" \
    --bundle-id "$BUNDLE" --key-pair-name "$KEY_NAME" --tags key=app,value=claude-blooded >/dev/null
  echo "creating instance $NAME ($BUNDLE, $BLUEPRINT, $ZONE)"
fi
until [ "$(lsail get-instance-state --instance-name "$NAME" --query state.name --output text)" = running ]; do sleep 5; done

# Static IP: free while attached, survives stop/start, so a domain can point at it
lsail get-static-ip --static-ip-name "$IP_NAME" >/dev/null 2>&1 || lsail allocate-static-ip --static-ip-name "$IP_NAME" >/dev/null
if [ "$(lsail get-static-ip --static-ip-name "$IP_NAME" --query staticIp.attachedTo --output text)" != "$NAME" ]; then
  lsail attach-static-ip --static-ip-name "$IP_NAME" --instance-name "$NAME" >/dev/null
fi
IP=$(lsail get-static-ip --static-ip-name "$IP_NAME" --query staticIp.ipAddress --output text)

lsail put-instance-public-ports --instance-name "$NAME" --port-infos \
  fromPort=22,toPort=22,protocol=tcp fromPort=80,toPort=80,protocol=tcp fromPort=443,toPort=443,protocol=tcp >/dev/null
echo "instance $NAME running at $IP (ports 22, 80, 443 open)"

SSH=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -i "$KEY_FILE")
for _ in $(seq 1 40); do "${SSH[@]}" "ec2-user@$IP" true 2>/dev/null && break; sleep 5; done
scp -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "$(dirname "$0")/bootstrap.sh" "ec2-user@$IP:/tmp/bootstrap.sh"
"${SSH[@]}" "ec2-user@$IP" "sudo REPO='$REPO' bash /tmp/bootstrap.sh"
echo
echo "site: http://$IP   ssh: ssh -i $KEY_FILE ec2-user@$IP"
echo "next: set keys in /etc/claude-blooded.env on the server, then sudo systemctl restart claude-blooded-api claude-blooded-worker"
