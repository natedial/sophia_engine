COMPOSE_FILE := infra/docker-compose.yml
ENV_FILE := infra/.env
ENV_EXAMPLE := infra/.env.example
COMPOSE := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)

.PHONY: init up down logs ps build restart

init:
	@test -f $(ENV_FILE) || cp $(ENV_EXAMPLE) $(ENV_FILE)

up: init
	$(COMPOSE) up -d --build

down: init
	$(COMPOSE) down

logs: init
	$(COMPOSE) logs -f

ps: init
	$(COMPOSE) ps

build: init
	$(COMPOSE) build

restart: init
	$(COMPOSE) down
	$(COMPOSE) up -d --build
