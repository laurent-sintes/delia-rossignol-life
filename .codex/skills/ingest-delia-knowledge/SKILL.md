---
name: ingest-delia-knowledge
description: Importer un CV, diplôme, document, note, archive ou site web relatif à Délia Rossignol, en extraire des propositions traçables et conduire leur validation humaine avant mise à jour de la base de connaissances. Utiliser cette skill pour toute ingestion, réingestion, analyse de source, crawl de site, contrôle de doublon ou contradiction.
---

# Ingestion des connaissances de Délia

## Procédure

1. Lire `AGENTS.md` et respecter la séparation source, proposition et connaissance validée.
2. Placer un original local dans `private/originals/`; ne jamais le committer.
3. Créer son manifeste avec `python scripts/delia_life.py manifest <fichier> --kind <type> --output data/sources/manifests/<id>.json`.
4. Pour un site, lancer `python scripts/delia_life.py slurp-site <url> --output private/website-archives/<nom>`. Rester sur le même domaine et conserver le manifeste produit.
5. Extraire des propositions atomiques dans `data/review/queue/`. Fournir pour chacune une source, un emplacement, un extrait, une classification et un niveau de confiance.
6. Classer chaque proposition comme `fact`, `claim` ou `inference`. Ne jamais transformer une inférence en fait.
7. Lancer `python scripts/delia_life.py check`. Présenter les doublons, contradictions et propositions à l'utilisateur.
8. Attendre une décision humaine avant d'exécuter `review`. Utiliser `accept`, `edit` ou `reject` et renseigner le relecteur.
9. Appliquer uniquement une proposition validée avec la commande Python dédiée. Ne pas éditer directement la connaissance cible.

## Extraction

Utiliser les outils spécialisés disponibles pour lire PDF, DOCX, images ou OCR. Pour un site, analyser aussi le ton, la posture, les activités et les éléments visuels, mais enregistrer ces analyses comme `inference` tant qu'elles ne sont pas validées.

Ne pas recopier une source entière dans une proposition. Conserver seulement l'extrait nécessaire à la preuve.
