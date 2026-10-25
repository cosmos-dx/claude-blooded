#!/bin/bash
# Launch the reels server on EC2 and bootstrap it.
# Uses whatever AWS credentials are in the environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION).
#
#   SUBNET_ID=subnet-... SECURITY_GROUP_ID=sg-... ./deploy/provision_ec2.sh
#
# Optional: INSTANCE_TYPE (t4g.nano), KEY_NAME (claude-blooded), DISK_GB (12), NAME (claude-blooded),
#           REPO (git URL), EXTRA_SECURITY_GROUP_ID (a group the database already trusts).
set -euo pipefail
: "${SUBNET_ID:?set SUBNET_ID}"
: "${SECURITY_GROUP_ID:?set SECURITY_GROUP_ID}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t4g.nano}"
KEY_NAME="${KEY_NAME:-claude-blooded}"
DISK_GB="${DISK_GB:-12}"
NAME="${NAME:-claude-blooded}"
REPO="${REPO:-https://github.com/cosmos-dx/claude-blooded.git}"
KEY_FILE="$HOME/.ssh/$KEY_NAME.pem"
SG_JSON="\"$SECURITY_GROUP_ID\"${EXTRA_SECURITY_GROUP_ID:+,\"$EXTRA_SECURITY_GROUP_ID\"}"   # not $GROUPS: bash reserves it

case "$INSTANCE_TYPE" in t4g.*|c7g.*|m7g.*|c8g.*) ARCH=arm64 ;; *) ARCH=x86_64 ;; esac

if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
  mkdir -p "$HOME/.ssh"
  aws ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 --query KeyMaterial --output text > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "created key pair $KEY_NAME -> $KEY_FILE"
fi

AMI=$(aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023.*-kernel-*-$ARCH" "Name=state,Values=available" \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
echo "AMI: $AMI ($ARCH)"

IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name "$KEY_NAME" \
  --network-interfaces "[{\"DeviceIndex\":0,\"SubnetId\":\"$SUBNET_ID\",\"Groups\":[$SG_JSON],\"AssociatePublicIpAddress\":true}]" \
  --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,DeleteOnTermination=true}" \
  --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
  --credit-specification CpuCredits=standard \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=app,Value=claude-blooded}]" \
  --query 'Instances[0].InstanceId' --output text)
echo "instance: $IID (waiting for it to run)"
aws ec2 wait instance-running --instance-ids "$IID"
IP=$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "public IP: $IP"

for i in $(seq 1 30); do ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -i "$KEY_FILE" "ec2-user@$IP" true 2>/dev/null && break; sleep 5; done
scp -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "$(dirname "$0")/bootstrap.sh" "ec2-user@$IP:/tmp/bootstrap.sh"
ssh -i "$KEY_FILE" "ec2-user@$IP" "sudo REPO='$REPO' bash /tmp/bootstrap.sh"
echo
echo "server: http://$IP   ssh: ssh -i $KEY_FILE ec2-user@$IP"
echo "next: fill /etc/claude-blooded.env on the server, then sudo systemctl restart claude-blooded-api claude-blooded-worker"
