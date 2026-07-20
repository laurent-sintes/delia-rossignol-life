---
name: ingest-delia-knowledge
description: Importer un CV, diplôme, document, note, archive ou site web relatif à Délia Rossignol, en extraire des propositions traçables et conduire leur validation humaine avant mise à jour de la base de connaissances. Utiliser cette skill pour toute ingestion, réingestion, analyse de source, crawl de site, contrôle de doublon ou contradiction.
---

# Ingestion des connaissances de Délia

## Procédure

1. Lire `AGENTS.md` et respecter la séparation source, proposition et connaissance validée.
2. Placer un original local dans `private/originals/` et le conserver pour le prochain commit. Ce répertoire est versionné mais exclu de GitHub Pages.
3. Créer son manifeste avec `python scripts/delia_life.py manifest <fichier> --kind <type> --output data/sources/manifests/<id>.json`.
4. Pour un site, lancer `python scripts/delia_life.py crawl-site <url> --output private/website-archives/<nom>`. Rester sur le même domaine et conserver le manifeste produit.
5. Extraire des propositions atomiques dans `data/review/queue/`. Fournir pour chacune une source, un emplacement, un extrait, une classification et un niveau de confiance.
6. Classer chaque proposition comme `fact`, `claim` ou `inference`. Ne jamais transformer une inférence en fait.
7. Pour chaque expérience, extraire une `mission` explicite et distincte des responsabilités. Si la source ne permet pas de l'établir, créer une question de validation au lieu de la déduire.
8. Pour chaque expérience, extraire une liste non vide de `responsibilities`, distincte de la mission. Si la source ne permet pas de l'établir, créer une question de validation au lieu de l'inventer.
9. Lancer `python scripts/delia_life.py check`. Présenter les doublons, contradictions et propositions à l'utilisateur.
10. Attendre une décision humaine avant d'exécuter `review`. Utiliser `accept`, `edit` ou `reject` et renseigner le relecteur.
11. Appliquer uniquement une proposition validée avec la commande Python dédiée. Ne pas éditer directement la connaissance cible.

Versionner avec l'ingestion l'original ou l'archive, le manifeste, les propositions et leur historique de validation. Ne jamais ajouter de secret technique, de cookie d'authentification, de clé privée ou de fichier `.env`.

## Extraction

Utiliser les outils spécialisés disponibles pour lire PDF, DOCX, images ou OCR. Pour un site, analyser aussi le ton, la posture, les activités et les éléments visuels, mais enregistrer ces analyses comme `inference` tant qu'elles ne sont pas validées.

Ne pas recopier une source entière dans une proposition. Conserver seulement l'extrait nécessaire à la preuve.
