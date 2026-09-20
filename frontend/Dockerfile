FROM node:22-alpine

WORKDIR /app
RUN apk add --no-cache wget
COPY package.json package-lock.json* /app/
RUN npm install
COPY . /app
ARG VITE_API_BASE=http://localhost:8000
ARG VITE_API_KEY=change-me
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build
EXPOSE 5173
CMD ["npm", "run", "preview"]
