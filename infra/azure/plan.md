# Azure Infrastructure Deployment Plan

## Overview

The Linux Bias Docs Enforcer app will run as a scalable, resilient, and secure cloud deployment in Azure using Azure Kubernetes Service (AKS), Azure PostgreSQL Flexible Server, Azure OpenAI, and Azure Key Vault. This document outlines the requirements for deploying that infrastructure in a fully automated fashion.

## General requirements

- All infrastructure should be configured using Bicep templates.
- An interactive script should be provided that can allow for selection of the Azure subscription, resource group, and region for deployment. Each of these parameters should be passable as a command line argument but if not provided should be prompted by the script, with defaults set to allow for the user to simply hit enter to confirm. The defaults can be:
  - The active subscription in the Azure CLI
  - A resource group named "linuxfirstdocsrg-<date>" where <date> is the current date in YYYYMMDD format.
  - WestUS3 for the region.
- All components should be deployed into an Azure virtual network named 'linuxfirstdocs-vnet'.

## Service-specific requirements

### AKS

The AKS cluster should be configured as follows:

- Node-autoprovisioning enabled
- Workload identity enabled
- Service connector enabled
- CSI Secret Store enabled with Azure Key Vault provider
- App Routing enabled
- Cluster auto-upgrade enabled on the stable channel
- Node OS upgrade enabled
- KEDA enabled
- The API server should have a public endpoint

By default, the cluster should be named "linuxfirstdocs-aks" but the user should have the option to change this if running the interactive script.

### Azure PostgreSQL

The Azure PostgreSQL DB should be configured as follows:

- A Flexible Server on the burstable tier using the Standard_B2s SKU.
- 32GiB storage
- Entra and password auth enabled
- No public access
- The default resource name should be linuxfirstdocs-pgsql

### Azure OpenAI

The Azure OpenAI instance should configured as follows:

- The SKU should be S0
- The model should be GPT-4 (latest available version)
- The default resource name should be linuxfirstdocs-aoai

### Azure Key Vault (optional)

If the user wishes to create a new Key Vault, it should be configured as follows:

- The default resource name should be linuxfirstdocs-akv

Alternatively, they have the option to connect to an existing instance.

### Azure Container Registry (optional)

If the user wishes to create a new Azure Container Registry (ACR), it should be configured as follows:

- The SKU should be Standard
- The default resource name should be linuxfirstdocs-acr

Alternatively, they should have the option to connect to an existing one.

### Azure Monitor and Observability

The deployment should include a comprehensive monitoring solution:

- **Azure Monitor Workspace** - Fully managed Prometheus service for metrics collection
- **Azure Managed Grafana** - Visualization and dashboards for AKS and application metrics  
- **Log Analytics Workspace** - Centralized logging for all services
- **Application Insights** - Application performance monitoring
- Pre-configured dashboards for AKS, PostgreSQL, and application metrics
- Alert rules and action groups for proactive monitoring

### Microsoft Defender Security

Microsoft Defender should be enabled across all services for comprehensive security:

- **Microsoft Defender for Cloud** - Enhanced security posture management
- **Microsoft Defender for Containers** - AKS cluster and workload protection
- **Microsoft Defender for PostgreSQL** - Database threat protection
- **Microsoft Defender for Key Vault** - Secrets and key management security
- **Microsoft Defender for Container Registries** - Container image vulnerability scanning
- **Azure Policy** - Security compliance and governance policies

## Inter-service connectivity

Apps running in the AKS cluster should be able to connect to the DB, AKV, and AOAI instances via Azure Service Connector using managed identities and workload identity. AKS should also be able to pull from the ACR instance that we create or the one the user specifies without using passwords. All connections should use private endpoints where possible for enhanced security.