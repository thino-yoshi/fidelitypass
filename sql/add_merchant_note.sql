-- Note privée du commerçant sur un client, stockée sur sa carte de fidélité.
-- Une carte est unique par (merchant_id, client_id), donc une colonne suffit.
-- À lancer une fois dans Supabase → SQL Editor.

ALTER TABLE loyalty_cards
  ADD COLUMN IF NOT EXISTS merchant_note text;
