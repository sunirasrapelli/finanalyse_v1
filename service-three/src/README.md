# service-three — Java Spring Boot (Maven)

> **Example service.** Delete this folder if your team doesn't need a Java service,
> or keep it and replace the source code with your own.

## Source layout

```
service-three/
├── config/
│   ├── deploy.yaml           ← pipeline + Helm config (edit this)
│   └── secrets.json          ← GitHub secret mappings (edit this)
├── src/
│   └── main/
│       ├── java/
│       │   └── com/yourteam/
│       │       └── Application.java
│       └── resources/
│           └── application.yaml
├── pom.xml                   ← place at service root (next to Dockerfile)
└── mvnw / mvnw.cmd           ← Maven wrapper (optional)
```

## Required `pom.xml` snippet

```xml
<parent>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-parent</artifactId>
  <version>3.3.0</version>
</parent>

<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
  </dependency>
</dependencies>
```

## Required `application.yaml` for health probes

```yaml
management:
  endpoint:
    health:
      probes:
        enabled: true
  health:
    livenessState:
      enabled: true
    readinessState:
      enabled: true
```

## Local dev

```bash
./mvnw spring-boot:run
```

## Private Maven dependencies

Create a `GIT_TOKEN` repo secret (PAT with `read:packages`). The pipeline injects it as a BuildKit secret into `~/.m2/settings.xml`.

## To rename this service

1. Rename the folder: `mv service-three service-my-name`
2. Update `config/deploy.yaml`: set `helmReleaseName`, `namespace`, and the ingress host
