FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y fontconfig fonts-dejavu-core
WORKDIR /app
COPY app.jar /app/app.jar
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
