-- Convergence bnc-shaper -> bnc-kb (strategie A).
-- Objectif: laisser le moteur d'ingestion bnc-shaper (graphe type + tiers semantiques
-- + reconciliation incrementale) ecrire DANS le store bnc-kb, sans reecrire son
-- ingestion. On relache les contraintes propres a la taxonomie fermee de bnc-kb
-- (5 kinds, dichotomie container/leaf) et on enrichit chunks + liens pour porter le
-- modele shaper (13 kinds, 16 edge kinds, tiers, hash de contenu, versions).
--
-- bnc-kb continue de fonctionner inchange: son parser AsciiDoc produit toujours des
-- noeuds valides, et ses requetes (search / spec / links) lisent ces colonnes
-- additives. Seule la garantie container_vs_document est assouplie (voir 2).

-- 1. node.kind: ENUM ferme (5) -> TEXT (taxonomie OUVERTE shaper: 13 kinds metier).
--    Les CHECK et index PARTIELS de bnc-kb encapsulent des litteraux types node_kind
--    ('capability'::node_kind ...). Apres le cast en text ils deviendraient
--    "text = node_kind" (operateur inexistant). On les retire d'abord, on change le
--    type, puis on recree ceux que bnc-kb conserve (avec litteraux text).
ALTER TABLE node DROP CONSTRAINT IF EXISTS container_vs_document;
ALTER TABLE node DROP CONSTRAINT IF EXISTS capability_is_root;
DROP INDEX IF EXISTS uq_capability_slug;
DROP INDEX IF EXISTS uq_business_function_parent_slug;

ALTER TABLE node ALTER COLUMN kind TYPE text USING kind::text;

-- 2. CHECK container/leaf: NON recree. Il assume capability/business_function (sans
--    body) vs document/decision_record/risk (avec body+dimension); aucun noeud shaper
--    (Feature, REQ, Entity, Capability, Control, Risk, ...) n'entre dans une branche.
--    Assouplissement de gouvernance assume pour la convergence. Les cles naturelles
--    et l'invariant racine de bnc-kb sont recrees (litteraux text desormais).
ALTER TABLE node ADD CONSTRAINT capability_is_root
    CHECK (kind <> 'capability' OR parent_id IS NULL);
CREATE UNIQUE INDEX uq_capability_slug
    ON node (slug) WHERE kind = 'capability';
CREATE UNIQUE INDEX uq_business_function_parent_slug
    ON node (parent_id, slug) WHERE kind = 'business_function';

-- 3. node.content_hash: empreinte de contenu pour le diff incremental (noeud
--    ajoute / modifie / supprime se decide par comparaison de hash).
ALTER TABLE node ADD COLUMN IF NOT EXISTS content_hash text;

-- 4. node_chunk_embedding: tiers semantiques shaper (vs fenetres 200 mots), texte du
--    chunk, hash + versions = cle composite qui pilote le re-embedding selectif.
ALTER TABLE node_chunk_embedding ADD COLUMN IF NOT EXISTS tier text;
ALTER TABLE node_chunk_embedding ADD COLUMN IF NOT EXISTS chunk_text text;
ALTER TABLE node_chunk_embedding ADD COLUMN IF NOT EXISTS content_hash text;
ALTER TABLE node_chunk_embedding ADD COLUMN IF NOT EXISTS embedding_model_version text;
ALTER TABLE node_chunk_embedding ADD COLUMN IF NOT EXISTS pipeline_version text;
CREATE INDEX IF NOT EXISTS idx_node_chunk_tier ON node_chunk_embedding (tier);

-- 5. spec_link: un edge shaper porte TOUJOURS la ref textuelle (dst_ref) ET, une fois
--    resolue, l'id interne (dst_id), plus un drapeau pending (ref pas encore resolue).
--    Le XOR interne/externe de bnc-kb l'interdit -> on le retire et on ajoute dst_ref
--    + pending. La cle d'unicite dedup desormais sur (src, dst_id, dst_ref, rel) pour
--    que deux refs pending distinctes (dst_id NULL) ne se telescopent pas.
ALTER TABLE spec_link ADD COLUMN IF NOT EXISTS dst_ref text;
ALTER TABLE spec_link ADD COLUMN IF NOT EXISTS pending boolean NOT NULL DEFAULT false;
ALTER TABLE spec_link DROP CONSTRAINT IF EXISTS dst_internal_xor_external;
ALTER TABLE spec_link DROP CONSTRAINT IF EXISTS uq_edge;
ALTER TABLE spec_link ADD CONSTRAINT uq_edge
    UNIQUE NULLS NOT DISTINCT (src_id, dst_id, dst_ref, rel);

-- 6. link_type: whitelist gouvernee etendue aux 16 edge kinds shaper. Les codes sont
--    les valeurs on-disk (tirets compris). bnc-kb conserve sa gouvernance des types
--    de lien; 'realizes' (deja seede) est ignore par ON CONFLICT.
INSERT INTO link_type (code, label) VALUES
    ('contains', 'Contains'),
    ('affects-entity', 'Affects Entity'),
    ('performed-by', 'Performed By'),
    ('integrates-with', 'Integrates With'),
    ('broader', 'Broader'),
    ('conflicts-with', 'Conflicts With'),
    ('refines', 'Refines'),
    ('satisfies', 'Satisfies'),
    ('addresses', 'Addresses'),
    ('constrains', 'Constrains'),
    ('realizes', 'Realizes'),
    ('serves', 'Serves'),
    ('governed-by', 'Governed By'),
    ('threatens', 'Threatens'),
    ('mitigated-by', 'Mitigated By'),
    ('accepted-by', 'Accepted By')
ON CONFLICT (code) DO NOTHING;
