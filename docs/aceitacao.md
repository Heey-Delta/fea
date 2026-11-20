# Critérios de aceitação → testes (Task 26)

Cada critério tem ao menos um teste automático. Rodar tudo:
`TEST_DATABASE_URL=postgresql://... uv run pytest -q` (precisa de Postgres, FFmpeg e Tesseract; o CI roda igual).

## Produto (v2.1, seção 0.8)

| # | Critério | Testes |
|---|---|---|
| 1 | Duas operações com configurações diferentes nos mesmos motores | `test_operations.py::test_duplicate_copies_config_as_draft`, `test_editing.py::test_page_save_and_reject`, `test_render_job.py::test_preset_outside_network_rules_is_refused` (o preset vem da versão de cada operação) |
| 2 | Play com X gera execução rastreável | `test_fishing.py::test_play_from_the_interface`, `test_fishing.py::test_play_uses_fishing_defaults_and_enqueues_once` |
| 3 | Mesmos registros na fila da operação e na geral | `test_acceptance.py::test_c03_same_records_in_operation_and_general_queue` |
| 4 | Duplicados, inválidos ou sem autorização não contam | `test_fishing.py::test_collect_applies_every_rule`, `test_fishing.py::test_source_without_permission_is_pending_and_not_downloaded` |
| 5 | Aprovar um conjunto e distribuir só os selecionados | `test_approval.py::test_bulk_from_the_queue`, `test_acceptance.py::test_c05_only_selected_videos_are_distributed` |
| 6 | Intervalo zero libera tudo, respeitando limites | `test_acceptance.py::test_c06_interval_zero_releases_all_within_limits` |
| 7 | Intervalo positivo gera horários progressivos | `test_publish.py::test_rotation_alternates_channels_and_respects_interval` |
| 8 | "Primeira imediata" muda o primeiro horário de cada conta | `test_acceptance.py::test_c08_first_immediate_changes_first_slot_per_account` |
| 9 | Várias contas: uma tarefa por vídeo × conta | `test_acceptance.py::test_c09_one_job_per_video_and_account` |
| 10 | Falha numa plataforma não repete os sucessos | `test_acceptance.py::test_c10_failure_does_not_repeat_successes`, `test_publish.py::test_auth_error_marks_account_and_waits` |
| 11 | Limite atingido: agenda o máximo e deixa o resto pendente com motivo | `test_publish.py::test_all_mode_window_daily_limit_and_capacity`, `test_publish.py::test_pending_capacity_is_reevaluated` |
| 12 | Repetir um pedido não duplica publicações | `test_publish.py::test_request_key_is_idempotent`, `test_publishing_web.py::test_new_publication_preview_and_create` |

## Editor Nível 1 (`docs/editor-nivel-1.md`, seção 18)

| # | Critério | Testes |
|---|---|---|
| 1 | Recebe resoluções diferentes | `test_editor.py::test_every_fit_produces_the_standard` |
| 2 | Horizontais, verticais e quadrados | `test_editor.py::test_every_fit_produces_the_standard` (parametrizado por formato) |
| 3 | Três modos de enquadramento | `test_editor.py::test_every_fit_produces_the_standard`, `test_editor.py::test_contain_keeps_background_color` |
| 4 | Converte para o padrão configurado | `test_editor.py::test_full_hd_vertical_output`, `test_editor.py::test_image_becomes_video` |
| 5 | Importa máscaras PNG | `test_render_job.py::test_mask_import_validation`, `test_editing.py::test_mask_upload_and_versions` |
| 6 | Valida os PNG | `test_render_job.py::test_mask_import_validation`, `test_editing.py::test_mask_upload_and_versions` |
| 7 | Aplica máscaras sobrepostas | `test_editor.py::test_mask_is_applied_over_the_video` |
| 8 | Posição e escala da máscara | `test_editor.py::test_mask_with_other_size_is_adjusted_with_warning` |
| 9 | Opacidade | `test_editor.py::test_mask_opacity` |
| 10 | Insere textos | `test_editor.py::test_text_is_wrapped_and_shrunk` |
| 11 | Logotipos e elementos | `test_editor.py::test_element_goes_to_its_corner` |
| 12 | Configurações de áudio | `test_editor.py::test_audio_remove`, `test_editor.py::test_audio_replace_with_fades`, `test_editor.py::test_silent_source_warns_and_required_audio_blocks` |
| 13 | Salva presets por operação | `test_editing.py::test_page_save_and_reject` |
| 14 | Versiona presets e máscaras | `test_operations.py::test_saving_creates_new_immutable_version`, `test_render_job.py::test_mask_version_is_recorded` |
| 15 | Vários vídeos em lote | `test_render_job.py::test_render_job_through_the_queue`, `test_fishing.py::test_heat_criteria_picks_highest_scores` |
| 16 | Tarefas registradas individualmente | `test_queue.py`, `test_render_job.py::test_render_job_through_the_queue` |
| 17 | Identifica erros de renderização | `test_editor.py::test_qc_blocks_wrong_output`, `test_render_job.py::test_blocking_qc_goes_to_needs_fix` |
| 18 | Permite reprocessamento | `test_render_job.py::test_process_error_retries_then_needs_fix`, `test_approval.py::test_reject_and_new_version` |
| 19 | Preserva os originais | `test_render_job.py::test_new_version_never_overwrites_and_clears_approval` |
| 20 | Encaminha à aprovação os válidos | `test_render_job.py::test_render_goes_to_edited_queue` |

## Arquitetura e reprodutibilidade

- 26.3 O core não importa `networks/`: `test_editor.py::test_core_never_imports_networks`.
- 26.4 Mesmo original + mesma versão de preset e máscara = mesmos quadros: `test_acceptance.py::test_render_is_reproducible`.
