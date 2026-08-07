from __future__ import annotations


def effective_psr_dates_sql() -> str:
    return """
        SELECT
            p.*,
            CASE
                WHEN do.override_status = 'excluded' THEN NULL
                WHEN do.override_status = 'active' AND do.corrected_value IS NOT NULL THEN do.corrected_value
                ELSE p.response_date
            END AS effective_response_date,
            do.override_status AS date_override_status,
            do.corrected_value AS date_corrected_value
        FROM psr_responses p
        LEFT JOIN date_overrides do ON do.entity_type = 'psr_responses'
            AND do.field_name = 'response_date'
            AND (
                do.source_record_id = p.source_record_id
                OR (do.source_record_id IS NULL AND do.entity_id = p.psr_id)
            )
    """
