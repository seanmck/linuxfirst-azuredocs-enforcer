# Parse arguments
DEPLOY_POSTGRES=false
for arg in "$@"; do
  if [ "$arg" = "--local" ]; then
    DEPLOY_POSTGRES=true
  fi
done

# Apply the namespace
kubectl apply -f k8s/namespace.yaml

# Deploy Postgres only if --local is passed
if [ "$DEPLOY_POSTGRES" = true ]; then
  echo "Note: postgres.yaml has been removed. Use Azure Database for PostgreSQL instead."
fi

# Deploy Redis configuration and service for shared session storage
kubectl apply -f k8s/redis-config.yaml
kubectl apply -f k8s/redis.yaml

# Deploy RabbitMQ
kubectl apply -f k8s/rabbitmq.yaml

# Deploy the Bias Scoring Service
kubectl apply -f k8s/bias-scoring-service-keda.yaml

# Deploy the web UI
kubectl apply -f k8s/webui.yaml

# Deploy ingress for HTTPS access
kubectl apply -f k8s/webui-ingress.yaml
