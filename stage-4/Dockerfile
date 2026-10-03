# Pocketful stage 4. Build: docker build -t pocketful-s4 .   Run: docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
COPY web ./web
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/pocketful .

# Static binary, no runtime dependencies: nothing to fetch and nothing to shell into.
# The browser UI, its scripts, styles and fonts are embedded in the binary (go:embed web).
FROM scratch
COPY --from=build /out/pocketful /pocketful
USER 65532:65532
ENV PORT=8080
EXPOSE 8080
ENTRYPOINT ["/pocketful"]
