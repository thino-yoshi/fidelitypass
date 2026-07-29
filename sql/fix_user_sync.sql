-- ════════════════════════════════════════════════════════════════════════════
-- FIX : Synchroniser auth.users → public.users automatiquement
--
-- PROBLÈME : Les utilisateurs créés via Supabase Auth (signUp) existent dans
-- auth.users mais PAS dans public.users. Cela cause des FK violations lors
-- de l'insertion dans loyalty_cards (qui référence public.users).
--
-- À EXÉCUTER : Dans Supabase Dashboard → SQL Editor
-- ════════════════════════════════════════════════════════════════════════════

-- ── ÉTAPE 1 : Backfill des utilisateurs manquants ──────────────────────────
-- Insère tous les utilisateurs de auth.users qui n'existent pas dans public.users.
INSERT INTO public.users (id, email, user_type, name, password_hash, created_at)
SELECT
    au.id,
    COALESCE(au.email, 'user-' || SUBSTRING(au.id::text, 1, 8) || '@qarta.local') AS email,
    COALESCE(au.raw_user_meta_data->>'user_type', 'client') AS user_type,
    COALESCE(
        au.raw_user_meta_data->>'name',
        SPLIT_PART(au.email, '@', 1),
        'Client'
    ) AS name,
    'SUPABASE_AUTH' AS password_hash,
    au.created_at
FROM auth.users au
WHERE au.id NOT IN (SELECT id FROM public.users)
ON CONFLICT (id) DO NOTHING;

-- Vérifier combien ont été synchronisés
SELECT
    (SELECT COUNT(*) FROM auth.users) AS total_auth_users,
    (SELECT COUNT(*) FROM public.users) AS total_public_users;


-- ── ÉTAPE 2 : Trigger pour auto-sync les nouveaux signups ──────────────────
-- Crée une fonction qui copie auth.users → public.users à chaque INSERT.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER -- s'exécute avec les droits du propriétaire (postgres)
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (id, email, user_type, name, password_hash, created_at)
    VALUES (
        NEW.id,
        COALESCE(NEW.email, 'user-' || SUBSTRING(NEW.id::text, 1, 8) || '@qarta.local'),
        COALESCE(NEW.raw_user_meta_data->>'user_type', 'client'),
        COALESCE(
            NEW.raw_user_meta_data->>'name',
            SPLIT_PART(NEW.email, '@', 1),
            'Client'
        ),
        'SUPABASE_AUTH',
        NEW.created_at
    )
    ON CONFLICT (id) DO NOTHING;

    RETURN NEW;
END;
$$;

-- Supprimer l'ancien trigger s'il existe (idempotent)
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

-- Créer le trigger
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();


-- ── ÉTAPE 3 : Vérification ─────────────────────────────────────────────────
-- Vérifier que le trigger existe
SELECT
    tgname AS trigger_name,
    tgrelid::regclass AS table_name,
    tgenabled AS enabled
FROM pg_trigger
WHERE tgname = 'on_auth_user_created';

-- Vérifier que tous les auth.users sont bien dans public.users
SELECT
    au.id,
    au.email,
    pu.id IS NOT NULL AS exists_in_public
FROM auth.users au
LEFT JOIN public.users pu ON au.id = pu.id
ORDER BY au.created_at DESC
LIMIT 20;
