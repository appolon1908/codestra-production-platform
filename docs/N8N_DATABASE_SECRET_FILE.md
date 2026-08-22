# n8n database secret-file startup

n8n does not consume the deployment's `DB_POSTGRESDB_PASSWORD_FILE` variable directly. The protected Compose override reads the mounted Docker secret inside the container, exports it without logging it, and then replaces the shell with `n8n start`. The same wrapper loads the encryption key. Neither secret appears in Compose source, image layers, or command output.
