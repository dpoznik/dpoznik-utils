# Colors
GREEN := \033[0;32m
CYAN := \033[0;36m
BOLD_RED := \033[1;31m
BOLD_GREEN := \033[1;32m
BOLD_YELLOW := \033[1;33m
BOLD_CYAN := \033[1;36m
RESET_COLOR := \033[0m


## General
#----------------------------------------------------------------------
help:  ## Print this help message
	@grep -h -E '(\s|^)##\s' $(MAKEFILE_LIST) \
	| sed -E "s/^## (.*)/\n$$(printf "${BOLD_GREEN}")\1$$(printf "${RESET_COLOR}")/g" \
	| awk 'BEGIN {FS = ":.*?## "}; {printf "${CYAN}%-25s${RESET_COLOR} %s\n", $$1, $$2}'
	@echo


## Linting
#----------------------------------------------------------------------
init: install-hooks update-hooks  ## Install `pre-commit` hooks

install-hooks:  ## Install `pre-commit` hooks
	@$(MAKE) check-utility-install UTILITY=pre-commit
	@printf "\n${BOLD_GREEN}Installing pre-commit hooks${RESET_COLOR}...\n\n"
	pre-commit uninstall --hook-type pre-commit --hook-type commit-msg
	pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg

update-hooks:  ## Update `pre-commit` hooks
	@printf "\n${BOLD_GREEN}Updating pre-commit hooks${RESET_COLOR}...\n\n"
	pre-commit autoupdate

run-hooks:  ## Run pre-commit hooks
	pre-commit run

run-hooks-all:  ## Run pre-commit hooks on all files
	pre-commit run --all-files --color always

lint: run-hooks-all  ## Alias for run-hooks-all


## Environment checks
#----------------------------------------------------------------------
check-utility-install:  ## Error unless UTILITY is installed
	@if ! command -v $(UTILITY) &> /dev/null; then \
	    printf "\n${BOLD_RED}ERROR${RESET_COLOR}. \"$(UTILITY)\" is required.\n"; \
	    printf "To install: uv tool install ${UTILITY}\n\n"; \
	    exit 1; \
	fi
