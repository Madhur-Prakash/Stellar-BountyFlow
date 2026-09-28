# syntax=docker/dockerfile:1.7

# ---------- Build stage ----------
FROM node:22-alpine AS build
WORKDIR /app
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=true
RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN corepack install && pnpm install --frozen-lockfile

COPY . .
# Public, non-secret build-time configuration only.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN pnpm build

# ---------- Runtime stage ----------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1/index.html >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
