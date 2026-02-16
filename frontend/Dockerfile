FROM node:20-alpine AS builder

WORKDIR /app

ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG VITE_API_BASE_URL=/api/v1
ENV NPM_REGISTRY=${NPM_REGISTRY}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package.json package-lock.json ./
COPY tsconfig.json ./
COPY vite.config.ts ./
COPY index.html ./
COPY src ./src

RUN npm config set registry ${NPM_REGISTRY} \
    && if [ -n "$HTTP_PROXY" ]; then npm config set proxy "$HTTP_PROXY"; fi \
    && if [ -n "$HTTPS_PROXY" ]; then npm config set https-proxy "$HTTPS_PROXY"; fi \
    && if [ -n "$NO_PROXY" ]; then npm config set noproxy "$NO_PROXY"; fi \
    && npm ci \
    && npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
