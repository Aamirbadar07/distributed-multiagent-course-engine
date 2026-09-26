#!/usr/bin/env bash
# ==============================================================================
# Cloud Run Production Deployment Script
# Zero Hardcoded Secrets: Leverages Google Cloud IAM & Workload Identity.
# ==============================================================================
set -euo pipefail

# Configuration parameters with sensible production defaults
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-course-engine-swarm}"
SERVICE_ACCOUNT_NAME="${SERVICE_ACCOUNT_NAME:-course-engine-sa}"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "============================================================"
echo " Deploying Distributed Multi-Agent Course Engine to Cloud Run"
echo " Project:  ${PROJECT_ID}"
echo " Region:   ${REGION}"
echo " Service:  ${SERVICE_NAME}"
echo "============================================================"

if [ -z "${PROJECT_ID}" ]; then
    echo "ERROR: GOOGLE_CLOUD_PROJECT is not set and could not be detected from gcloud."
    echo "Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo "[1/5] Enabling required Google Cloud APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    aiplatform.googleapis.com \
    --project="${PROJECT_ID}"

echo "[2/5] Setting up dedicated least-privilege Service Account..."
SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
        --display-name="Course Creation Agent Swarm Runner" \
        --project="${PROJECT_ID}"
    echo "Created service account: ${SA_EMAIL}"
else
    echo "Service account ${SA_EMAIL} already exists."
fi

echo "[3/5] Granting Vertex AI User permission..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/aiplatform.user" \
    --condition=None >/dev/null

echo "[4/5] Building container image via Google Cloud Build..."
gcloud builds submit --tag "${IMAGE_TAG}" --project="${PROJECT_ID}" .

echo "[5/5] Deploying container to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_TAG}" \
    --platform=managed \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --service-account="${SA_EMAIL}" \
    --memory=2Gi \
    --cpu=2 \
    --concurrency=80 \
    --timeout=900s \
    --min-instances=0 \
    --max-instances=10 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},LOG_LEVEL=INFO" \
    --no-allow-unauthenticated

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --platform=managed --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")

echo "============================================================"
echo " Deployment Successfully Completed!"
echo " Service Endpoint: ${SERVICE_URL}"
echo ""
echo " The service requires authentication: every request bills Vertex AI"
echo " tokens to this project, so it is not exposed publicly."
echo ""
echo " Grant a caller the invoker role:"
echo "   gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\"
echo "     --region=${REGION} --project=${PROJECT_ID} \\"
echo "     --member='user:CALLER@example.com' --role='roles/run.invoker'"
echo ""
echo " Then call it with an identity token:"
echo "   curl -X POST ${SERVICE_URL}/v1/orchestrator/generate \\"
echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
echo "     -H 'Content-Type: application/json' -d @samples/sample_input.json"
echo "============================================================"
