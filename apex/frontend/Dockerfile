FROM node:22-alpine AS build
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG BACKEND_URL=http://backend:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/live
ENV BACKEND_URL=$BACKEND_URL NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL NEXT_OUTPUT=standalone
RUN npm run build

FROM node:22-alpine
WORKDIR /srv
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /srv/.next/standalone ./
COPY --from=build /srv/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
