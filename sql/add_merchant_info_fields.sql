-- Champs "Info commerce" (écran v24) sur la table merchants.
-- opening_days = liste de jours, ex "Lun,Mar,Mer,Jeu,Ven"
-- opening_hours = créneau, ex "11:30-22:00"
-- À lancer une fois dans Supabase → SQL Editor.

ALTER TABLE merchants ADD COLUMN IF NOT EXISTS address       text;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS phone         text;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS website       text;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS opening_days  text;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS opening_hours text;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS description   text;
