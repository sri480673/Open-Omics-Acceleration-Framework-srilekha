# RELION 2D Classification on AWS Batch (Nextflow)
## Overview
This setup runs **RELION 2D classification** using **Nextflow + AWS Batch (EC2)**, where **each dataset runs as an isolated Batch job on a c7i.8xlarge instance**.

The final working solution explicitly uses:
* default ECS-optimized AMI
* EC2 Launch Template
* AWS Batch Managed Compute Environment

## Prerequisites (before starting)
1) AWS CLI configured:
   aws sts get-caller-identity

2) Region:
   `export AWS_REGION=us-east-2`

3) Tools installed:
   - Docker
   - Nextflow (and Java)
   - AWS CLI

4) Identify account id:
   `ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)`
   `echo "ACCOUNT_ID=$ACCOUNT_ID"`


## What the workflow does

Input datasets live under:
```bash
relion_data/
  ├── data_1/
  ├── data_2/
  ├── ...
```

* Nextflow discovers each `data_*` directory
* Each dataset is submitted as a **separate AWS Batch job**
* Each job:
   * Runs on **one EC2 instance** (c7i.8xlarge)
   * Executes `mpirun relion_refine_mpi` inside a container
   * Writes output under:
   ```bash
   Class2D/run_<dataset_id>
   ```
* Outputs are published to S3

* Jobs are fully isolated: no shared working directories, no cross-dataset interference.

## Why AMI matters

AWS Batch on EC2 runs containers via **ECS**.

For ECS to start containers correctly, the EC2 instance must have:
* ECS agent installed
* A working container runtime (Docker or containerd)
* Correct system configuration

## What went wrong initially
* Default Batch compute environment(default AMI and 30 GB root disk):
   * ECS agent present
* Result:
   * Batch jobs stuck in STARTING
   * No container logs
   * No visible runtime errors

When the root disk size alone was increased to 200 GB (keeping the default AMI):
* Jobs were able to move from STARTING → RUNNING
* RELION executions completed successfully

## Why Launch Template was required

When no launch template is provided, AWS Batch uses defaults:
* Default ECS-optimized AMI 
* Default root disk size 

This is often sufficient for **small images**, but **not** for RELION.

## RELION-specific requirements
* Container image size ≈ 30 GB
* Docker/containerd needs 2–3× image size during pull & unpack

## Without a launch template:
* Disk fills up
* Container runtime fails silently
* ECS agent cannot start tasks
## Launch Template fixed this by
* Increasing root volume to 200 GB (gp3)

## Final Architecture:
```bash
Nextflow
  ↓
AWS Batch Job Queue
  ↓
AWS Batch Compute Environment (EC2)
  ↓
EC2 instance (default ECS-optimized AMI)
  ↓
Container runtime pulls RELION image from ECR
  ↓
RELION execution inside container
  ↓
Outputs published to S3
```

## Build the RELION container and push to ECR

### 1) Build the Docker image locally:

From the folder containing the Dockerfile:

```bash
cd ..
cd build_docker/
docker build -t relion_common_scan:latest .
cd ../nextflow_relion
```

### 2) Create the ECR repository (one-time):

Create the ECR repo (skip if it already exists):
```bash
aws ecr create-repository --region us-east-2 --repository-name relion_common_scan
```
### 3) Authenticate Docker to ECR:
```bash
aws ecr get-login-password --region us-east-2 \
| docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com

```

### 4) Tag the image for ECR:
```bash
docker tag relion_common_scan:latest <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/relion_common_scan:latest
```
### 5) Push to ECR:

```bash
docker push <ACCOUNT_ID>.dkr.ecr.us-east-2.amazonaws.com/relion_common_scan:latest
```

## How to find Subnet IDs and Security Group ID
Console:
* VPC → Subnets → select two subnets → copy subnet-xxxx
* VPC → Security Groups → pick default SG or create one → copy sg-xxxx

## PART 1 — Create AWS Batch Environment (Default AMI + Default Disk)
### Step 1: Required IAM Roles (one-time)
#### 1. AWSBatchServiceRole

Used by AWS Batch to manage EC2/ECS.
Role name: `AWSBatchServiceRole`

Policy:
```bash
AWSBatchServiceRole
```
#### 2. ecsInstanceRole

Attached to EC2 instances launched by Batch.
Role name: `ecsInstanceRole`

Policies:

```bash
* AmazonEC2ContainerServiceforEC2Role
* AmazonEC2ContainerRegistryReadOnly
* AmazonS3FullAccess
```
## User permissions (what you had on your user)
### Minimum to run Nextflow + Batch jobs
```bash
AWSBatchFullAccess
AmazonS3FullAccess
AmazonEC2ContainerRegistryReadOnly
CloudWatchLogsReadOnlyAccess( optional but recommended)
```

### Only needed if creating infrastructure via CLI (Launch Template / CE / Queue)
They do need:
* permissions to create launch templates
* permissions to create compute environments / job queues
* iam:PassRole so Batch can use roles(`AWSBatchServiceRole` , `ecsInstanceRole`)

PassRole statement (put in a managed policy):
```bash
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PassBatchAndEcsRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::<ACCOUNT_ID>:role/AWSBatchServiceRole",
        "arn:aws:iam::<ACCOUNT_ID>:role/ecsInstanceRole"
      ]
    }
  ]
}
```
### Debugger (wants to prove disk size using describe-instances/volumes)

They need read-only EC2 permissions:

Minimum:
```bash
ec2:DescribeInstances

ec2:DescribeVolumes

ec2:DescribeLaunchTemplates 
```

If you want a minimal custom “disk proof” policy:

```bash
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2DiskProofReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes"
      ],
      "Resource": "*"
    }
  ]
}
```
### Step 2: Create Compute Environment (NO launch template)

This uses default ECS-optimized AMI and default disk (30 GB).
```bash
aws batch create-compute-environment \
  --region us-east-2 \
  --compute-environment-name relion-ce-default \
  --type MANAGED \
  --state ENABLED \
  --service-role arn:aws:iam::<ACCOUNT_ID>:role/AWSBatchServiceRole \
  --compute-resources '{
    "type":"EC2",
    "minvCpus":0,
    "desiredvCpus":0,
    "maxvCpus":256,
    "instanceTypes":["c7i.8xlarge"],
    "subnets":[
      "subnet-0cc85b462f56588f8",
      "subnet-03091d3d44b447382"
    ],
    "securityGroupIds":["sg-0ef47e9ad1b4f9271"],
    "instanceRole":"ecsInstanceRole"
  }'
```

### Step 3: Create Job Queue
```bash
aws batch create-job-queue \
  --region us-east-2 \
  --job-queue-name relion-default-queue \
  --priority 1 \
  --compute-environment-order order=1,computeEnvironment=relion-ce-default
```

### Step 4: Submit Nextflow Job

Run Nextflow pointing to `relion-default-queue`.

### Command to run:
```bash
nextflow run main.nf   -profile awsbatch_relion_2d   --relion_image $ACCOUNT_ID.dkr.ecr.us-east-2.amazonaws.com/relion_common_scan:latest   -ansi-log false
```     

Result:

Jobs remain in STARTING

Do not reach RUNNING

## PART 2 — Diagnose Why Job Is Stuck in STARTING
### Step 5: Get Job ID
```bash
JOB_ID=$(aws batch list-jobs \
  --region us-east-2 \
  --job-queue relion-default-queue \
  --job-status STARTING \
  --max-results 1 \
  --query "jobSummaryList[0].jobId" \
  --output text)

echo "JOB_ID=$JOB_ID"
```

### Step 6: Get ECS Container Instance
```bash
CI_ARN=$(aws batch describe-jobs \
  --region us-east-2 \
  --jobs "$JOB_ID" \
  --query "jobs[0].container.containerInstanceArn" \
  --output text)

CLUSTER_NAME=$(echo "$CI_ARN" | sed -E 's|.*container-instance/([^/]+)/.*|\1|')
CI_ID=$(echo "$CI_ARN" | sed -E 's|.*/([^/]+)$|\1|')
```

### Step 7: Describe Container Instance

```bash
aws ecs describe-container-instances \
  --region us-east-2 \
  --cluster "$CLUSTER_NAME" \
  --container-instances "$CI_ID" \
  --query "containerInstances[0].{
    agentConnected:agentConnected,
    dockerVersion:dockerVersion,
    ec2InstanceId:ec2InstanceId,
    amiId:attributes[?name=='ecs.ami-id'].value|[0]
  }" \
  --output table
```

Typical output:
```bash
agentConnected = true
```

ECS agent is alive.

### Step 8: Check Root Disk Size (PROOF)
```bash
EC2_ID=$(aws ecs describe-container-instances \
  --region us-east-2 \
  --cluster "$CLUSTER_NAME" \
  --container-instances "$CI_ID" \
  --query "containerInstances[0].ec2InstanceId" \
  --output text)

VOL_ID=$(aws ec2 describe-instances \
  --region us-east-2 \
  --instance-ids "$EC2_ID" \
  --query "Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId" \
  --output text)

aws ec2 describe-volumes \
  --region us-east-2 \
  --volume-ids "$VOL_ID" \
  --query "Volumes[0].{SizeGiB:Size,Type:VolumeType}" \
  --output table

```

Output:

SizeGiB = 30


Root cause identified: 30 GB disk is insufficient

## PART 3 — Fix: Use Launch Template with 200 GB Disk (Default AMI)

### Step 9: Create Launch Template (NO custom AMI)
```bash
aws ec2 create-launch-template \
  --region us-east-2 \
  --launch-template-name relion-ecs-200g \
  --launch-template-data '{
    "BlockDeviceMappings": [
      {
        "DeviceName": "/dev/xvda",
        "Ebs": {
          "VolumeSize": 200,
          "VolumeType": "gp3",
          "DeleteOnTermination": true
        }
      }
    ]
  }'
```

### Step 10: Create NEW Compute Environment (with 200 GB disk)

```bash
aws batch create-compute-environment \
  --region us-east-2 \
  --compute-environment-name relion-ce-200g \
  --type MANAGED \
  --state ENABLED \
  --service-role arn:aws:iam::<ACCOUNT_ID>:role/AWSBatchServiceRole \
  --compute-resources '{
    "type":"EC2",
    "minvCpus":0,
    "desiredvCpus":0,
    "maxvCpus":256,
    "instanceTypes":["c7i.8xlarge"],
    "subnets":[
      "subnet-0cc85b462f56588f8",
      "subnet-03091d3d44b447382"
    ],
    "securityGroupIds":["sg-0ef47e9ad1b4f9271"],
    "instanceRole":"ecsInstanceRole",
    "launchTemplate":{
      "launchTemplateName":"relion-ecs-200g",
      "version":"$Latest"
    }
  }'
```

### Step 11: Create NEW Job Queue
```bash
aws batch create-job-queue \
  --region us-east-2 \
  --job-queue-name relion-queue-200g \
  --priority 1 \
  --compute-environment-order order=1,computeEnvironment=relion-ce-200g
```

### Step 12: Rerun Nextflow

Update Nextflow config to use:

queue = `relion-queue-200g`


Result:
Jobs move from STARTING → RUNNING

