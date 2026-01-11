# Dev Environment GitHub OAuth Setup

This document explains how to set up GitHub OAuth for the dev environment.

## Overview

The dev environment (`dev.linuxdocs.seanmck.dev`) requires separate GitHub OAuth credentials from production to ensure OAuth state validation works correctly.

## Prerequisites

- Azure CLI installed and authenticated
- Access to the Azure Key Vault (`seanmckaksdemo`)
- GitHub organization admin access to create OAuth apps

## Step 1: Create a GitHub OAuth App for Dev

1. Go to GitHub Settings → Developer settings → OAuth Apps → New OAuth App
2. Fill in the details:
   - **Application name**: `Linux First Docs - Dev`
   - **Homepage URL**: `https://dev.linuxdocs.seanmck.dev`
   - **Authorization callback URL**: `https://dev.linuxdocs.seanmck.dev/auth/github/callback`
   - **Description**: `OAuth app for dev environment of Linux First Docs enforcer`

3. Click "Register application"
4. Note the **Client ID**
5. Click "Generate a new client secret" and note the **Client Secret** (you won't be able to see it again)

## Step 2: Store Credentials in Azure Key Vault

Store the OAuth credentials in Azure Key Vault with dev-specific secret names:

```bash
# Set your Key Vault name
KEY_VAULT_NAME="seanmckaksdemo"

# Store the dev OAuth client ID
az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "linuxdocs-dev-ghoauth-clientid" \
  --value "<YOUR_DEV_CLIENT_ID>"

# Store the dev OAuth client secret
az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "linuxdocs-dev-ghoauth-clientsecret" \
  --value "<YOUR_DEV_CLIENT_SECRET>"
```

## Step 3 (Optional): Create a Dev GitHub App

If you also want to test GitHub App functionality in dev, create a separate GitHub App:

1. Go to GitHub Settings → Developer settings → GitHub Apps → New GitHub App
2. Fill in the details:
   - **GitHub App name**: `linux-first-docs-dev`
   - **Homepage URL**: `https://dev.linuxdocs.seanmck.dev`
   - **Webhook URL**: `https://dev.linuxdocs.seanmck.dev/webhooks/github` (if applicable)
   - **Callback URL**: `https://dev.linuxdocs.seanmck.dev/auth/github/callback`
   - Set required permissions (similar to production app)

3. Note the **App ID** and generate a **Private Key**
4. Store them in Key Vault:

```bash
# Store the dev GitHub App ID
az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "linuxdocs-dev-ghapp-appid" \
  --value "<YOUR_DEV_APP_ID>"

# Store the dev GitHub App private key
az keyvault secret set \
  --vault-name "$KEY_VAULT_NAME" \
  --name "linuxdocs-dev-ghapp-privatekey" \
  --value "<YOUR_DEV_PRIVATE_KEY_CONTENT>"
```

## Step 4: Deploy Changes

After storing the secrets, the dev Kubernetes deployment will automatically use them on the next rollout:

```bash
# If you need to force a restart to pick up new secrets
kubectl rollout restart deployment/webui -n azuredocs-app
```

## Verification

1. Visit `https://dev.linuxdocs.seanmck.dev`
2. Click "Login with GitHub"
3. You should be redirected to GitHub OAuth authorization
4. After authorization, you should be redirected back to dev (not production)
5. Check that login succeeds without "Invalid state parameter" errors

## Troubleshooting

### "Invalid state parameter" error

This means the OAuth callback URL doesn't match. Verify:
- The GitHub OAuth app has `https://dev.linuxdocs.seanmck.dev/auth/github/callback` as the callback URL
- The Key Vault secrets are correctly named with `-dev-` prefix
- The webui deployment has restarted to pick up new secrets

### Check current configuration

```bash
# Check what secrets are mounted in the webui pod
kubectl exec -n azuredocs-app deployment/webui -- env | grep GITHUB

# Check the config status endpoint
curl https://dev.linuxdocs.seanmck.dev/auth/github/config-status
```

## Architecture

```
User → dev.linuxdocs.seanmck.dev/auth/github/login
  ↓
GitHub OAuth (dev app)
  ↓
Callback: dev.linuxdocs.seanmck.dev/auth/github/callback
  ↓
Dev Redis validates state ✅
  ↓
User authenticated
```

The key differences from production:
- Dev environment uses `linuxdocs-dev-ghoauth-*` secrets from Key Vault
- Production uses `linuxdocs-ghoauth-*` secrets
- Each environment has its own Redis, so state validation stays within the environment
