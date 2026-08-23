# Threshold assumptions

Generated from the authoritative catalog. Existing measured values were retained where documented: backup staleness 26 hours, backup remote free capacity 10 GiB, host capacity 90%, database critical saturation 90%, TLS critical expiry 7 days, and restore-test maximum age 30 days. Other values are deliberately conservative candidate thresholds.

No threshold in this file is claimed to be production-proven. Every rule carries `threshold_status=candidate_requires_post_deployment_tuning`. `for:` periods, grouping, and warning companions for capacity/latency controls limit alert storms. Safety-control violations intentionally use short durations. Warning and critical thresholds are distinct for integration latency, queue/retry backlog, database saturation, disk/inodes/recording storage, TLS expiry, remote backup capacity, and restore-test age.

| Alert | Critical threshold | `for` | Basis |
|---|---|---:|---|
| `CodestraMiddlewareUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraMiddlewareRestartLoop` | `3 restarts / 15m` | `5m` | candidate; tune after deployment |
| `CodestraOdoo19StagingUnavailable` | `service_up = 0` | `5m` | candidate; tune after deployment |
| `CodestraN8nStagingUnavailable` | `service_up = 0` | `5m` | candidate; tune after deployment |
| `CodestraKeycloakUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraPrivateCallbackReceiverUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraIntegrationLatencyHigh` | `p95 > 10s / 15m` | `15m` | candidate; tune after deployment |
| `CodestraQueueBacklogHigh` | `ready depth > 100 / 15m` | `15m` | candidate; tune after deployment |
| `CodestraRetryBacklogHigh` | `retry depth > 25 / 15m` | `15m` | candidate; tune after deployment |
| `CodestraDeadLetterBacklog` | `depth > 0 or growing / 5m` | `5m` | candidate; tune after deployment |
| `CodestraCallbackFailureRateHigh` | `failure ratio > 5% / 10m` | `10m` | candidate; tune after deployment |
| `CodestraDuplicateEventConflict` | `any conflict / 10m` | `2m` | candidate; tune after deployment |
| `CodestraEventOrderingConflict` | `any conflict / 10m` | `2m` | candidate; tune after deployment |
| `CodestraReconciliationDrift` | `drift records > 0 / 15m` | `15m` | candidate; tune after deployment |
| `CodestraAuthenticationFailureSurge` | `rate > 1/s / 10m` | `10m` | candidate; tune after deployment |
| `CodestraAuthorizationFailureSurge` | `rate > 0.5/s / 10m` | `10m` | candidate; tune after deployment |
| `CodestraDncFailClosedEvent` | `any event / 5m` | `1m` | candidate; tune after deployment |
| `CodestraTransferAuthorizationDenialSurge` | `3 denials / 5m` | `5m` | candidate; tune after deployment |
| `CodestraUnexpectedWorkflowActivation` | `active workflows > 0` | `1m` | candidate; tune after deployment |
| `CodestraUnexpectedWriteEnablement` | `write enablement > 0` | `1m` | candidate; tune after deployment |
| `CodestraUnexpectedSendEventsEnabled` | `SEND_EVENTS != 0` | `1m` | candidate; tune after deployment |
| `CodestraUnexpectedProductionCallbacksEnabled` | `PRODUCTION_CALLBACKS_ENABLED != 0` | `1m` | candidate; tune after deployment |
| `CodestraIntegrationArchitectureViolation` | `critical findings > 0` | `1m` | candidate; tune after deployment |
| `CodestraVicidialUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraAsteriskUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraTrunkUnavailable` | `trunk_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraCarrierAuthenticationFailure` | `any failure / 5m` | `2m` | candidate; tune after deployment |
| `CodestraUnexpectedActiveCall` | `active calls > 0` | `1m` | candidate; tune after deployment |
| `CodestraUnexpectedExternalDialingEnabled` | `EXTERNAL_DIAL_ENABLED != 0` | `1m` | candidate; tune after deployment |
| `CodestraEndpoint6101Unavailable` | `authorized registration = 0` | `2m` | candidate; tune after deployment |
| `CodestraEndpoint6101UnauthorizedRegistration` | `unauthorized registrations > 0` | `1m` | candidate; tune after deployment |
| `CodestraTurnUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraTurnAuthenticationFailure` | `any failure / 5m` | `2m` | candidate; tune after deployment |
| `CodestraWssHandshakeFailure` | `3 failures / 5m` | `5m` | candidate; tune after deployment |
| `CodestraIceFailure` | `3 failures / 5m` | `5m` | candidate; tune after deployment |
| `CodestraDtlsFailure` | `3 failures / 5m` | `5m` | candidate; tune after deployment |
| `CodestraSrtpFailure` | `3 failures / 5m` | `5m` | candidate; tune after deployment |
| `CodestraOneWayAudioIndication` | `2 indications / 10m` | `5m` | candidate; tune after deployment |
| `CodestraPacketLossExcessive` | `packet loss > 5% / 10m` | `10m` | candidate; tune after deployment |
| `CodestraJitterExcessive` | `jitter > 50ms / 10m` | `10m` | candidate; tune after deployment |
| `CodestraCallSetupLatencyExcessive` | `p95 > 8s / 10m` | `10m` | candidate; tune after deployment |
| `CodestraStuckAsteriskChannel` | `channel age > 1h` | `5m` | candidate; tune after deployment |
| `CodestraChannelCleanupFailure` | `any failure / 10m` | `5m` | candidate; tune after deployment |
| `CodestraPostgresqlUnavailable` | `database_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraMariadbUnavailable` | `database_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraRedisUnavailable` | `service_up = 0` | `2m` | candidate; tune after deployment |
| `CodestraDatabaseConnectionSaturation` | `connections > 90% / 10m` | `10m` | candidate; tune after deployment |
| `CodestraDiskCapacityCritical` | `used > 90% / 15m` | `15m` | candidate; tune after deployment |
| `CodestraInodeCapacityCritical` | `used > 90% / 15m` | `15m` | candidate; tune after deployment |
| `CodestraRecordingStorageCapacityCritical` | `used > 90% / 15m` | `15m` | candidate; tune after deployment |
| `CodestraContainerRestartLoop` | `3 restarts / 15m` | `5m` | candidate; tune after deployment |
| `CodestraClockDrift` | `offset > 100ms or unsynchronized` | `5m` | candidate; tune after deployment |
| `CodestraTlsCertificateExpiration` | `expires in < 7d` | `1h` | candidate; tune after deployment |
| `CodestraCredentialExpiration` | `expires in < 7d` | `1h` | candidate; tune after deployment |
| `CodestraConfigurationDrift` | `drift > 0 / 10m` | `10m` | candidate; tune after deployment |
| `CodestraRepositoryDrift` | `drift > 0 / 10m` | `10m` | candidate; tune after deployment |
| `CodestraLogIngestionFailure` | `ingestion_up = 0` | `5m` | candidate; tune after deployment |
| `CodestraBackupFailure` | `any failure / 1h` | `1m` | candidate; tune after deployment |
| `CodestraOffServerReplicationFailure` | `any failure / 1h` | `1m` | candidate; tune after deployment |
| `CodestraBackupChecksumFailure` | `any failure / 1h` | `1m` | candidate; tune after deployment |
| `CodestraBackupStale` | `age > 26h / 15m` | `15m` | candidate; tune after deployment |
| `CodestraRemoteBackupCapacityLow` | `free < 10GiB / 30m` | `30m` | candidate; tune after deployment |
| `CodestraBackupTimerDisabled` | `timer enabled = 0` | `5m` | candidate; tune after deployment |
| `CodestraBackupTimerFailed` | `timer failed > 0` | `2m` | candidate; tune after deployment |
| `CodestraRestoreTestAgeExceeded` | `age > 30d` | `1h` | candidate; tune after deployment |
| `CodestraEncryptionKeyExpiration` | `expires in < 30d` | `1h` | candidate; tune after deployment |
| `CodestraSshHostKeyMismatch` | `any mismatch / 1h` | `1m` | candidate; tune after deployment |
