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
  kubectl apply -f k8s/postgres.yaml
fi

# Deploy RabbitMQ
kubectl apply -f k8s/rabbitmq.yaml

# Deploy the MCP server
kubectl apply -f k8s/mcp-server.yaml

# Deploy the web UI
kubectl apply -f k8s/webui.yaml

# Expose the web UI via LoadBalancer (for cloud or minikube)
kubectl apply -f k8s/webui-lb.yaml
