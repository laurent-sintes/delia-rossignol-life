---
name: share-delia-offer-selection
description: Préparer, prévisualiser, envoyer avec autorisation et faire valider par Délia un message de revue d’une sélection d’offres, avec liens directs, site public et CV PDF joint. Utiliser cette skill lorsqu’il faut partager un classement, demander son avis, créer un brouillon Gmail, exécuter l’étape finale de la commande « envoi à Délia » ou traiter son retour structuré. Ne jamais envoyer un email sans autorisation explicite ; la commande exacte « envoi à Délia » constitue cette autorisation pour le rapport full produit pendant la même exécution.
---

# Partage d’une sélection d’offres

Préparer un paquet de brouillon traçable : texte, HTML, fichier `.eml`, manifeste, lien vers le site public et CV PDF joint. Le paquet ne déclenche aucun envoi.

## Workflow

1. Utiliser le rapport complet explicitement demandé ou, pour la commande « envoi à Délia », le `report_output_path` de la session full courante. Ne jamais substituer un ancien rapport si la session courante est incomplète. Afficher sans plafond toutes les offres classées, toutes les exclusions et toutes les annonces `pending_offers`. Regrouper les offres pertinentes dans l’ordre `priority`, `possible`, `informational`, puis les trier par pertinence décroissante dans chaque section.
   Refuser tout rapport portant `finalization_allowed: false`.
2. Vérifier le CV généré dans `site/assets/downloads/` avec `python scripts/delia_life.py check-documents`.
3. Préparer le brouillon, avec une adresse de destinataire explicitement fournie. Pour une sélection éditoriale, ajouter les identifiants des offres retenues ; le moteur les regroupe ensuite par section et les trie par score :

   ```powershell
   python scripts/delia_life.py prepare-offer-feedback-email generated/offer-search/YYYY-MM-DD-full.json --recipient "adresse-de-delia@example.com" --bcc "laurent.sintes74@gmail.com" --site-url "https://laurent-sintes.github.io/delia-rossignol-life/" --output generated/offer-feedback/YYYY-MM-DD
   ```

4. Ouvrir `offer-selection.txt`, `offer-selection.eml` et `manifest.json`, puis contrôler le destinataire, la copie cachée, les liens, le nombre d’offres et le PDF joint avant toute création de brouillon distant.
5. Pour une modification du classement, des offres ou du message, exécuter `python scripts/repo_flow.py review-operational` : ce contrôle vérifie le code et les données sans régénérer le CV ni reconstruire le site.
6. Si un connecteur de messagerie est disponible, créer un brouillon distant à partir de `offer-selection.eml`. L’envoyer seulement après une instruction explicite de l’utilisateur. La commande exacte « envoi à Délia » autorise l’envoi du message issu du scan full de la même exécution ; toute correction ultérieure du destinataire ou du contenu exige une nouvelle confirmation.
7. À réception de la réponse de Délia, séparer ses avis sur les offres de tout fait de carrière, puis utiliser le workflow de revue avant de modifier la stratégie de recherche.

## Règles

- Pour chaque offre, afficher un en-tête constant : secteur d’activité, mission / poste, salaire proposé (ou « non communiquée »), pertinence sur 100, puis contrat et lieu. Terminer par le « Point de vigilance » éventuel en orange dans le HTML. Ne jamais inclure de seuil salarial, contrainte familiale ou détail sensible dans le message.
- Afficher les trois sections non vides avec les titres « Il faut répondre, ça matche et tu as des chances d’un retour positif », « Tu peux répondre, on ne sait jamais » et « Je te les mets pour info, mais il y a peu de chances ». Conserver une numérotation globale stable entre les sections.
- Après ces trois sections, afficher « Offres probablement actives à revérifier » pour les seules annonces `pending`. Introduire cette annexe par une explication claire : ces annonces ont été rencontrées dans la recherche actuelle, mais leur lien détaillé a renvoyé une erreur ou bloqué l’accès au contenu. Préciser que cela ne signifie ni qu’elles sont fermées ni qu’elles sont incompatibles. Ne pas les numéroter avec la sélection, ne pas afficher de score et préciser ensuite le motif propre à chaque offre ainsi que le lien disponible. Une annonce actuellement accessible uniquement sur LinkedIn, Indeed, Hellowork ou une page listant plusieurs offres reste dans sa section classée avec un point de vigilance; l’absence de page employeur ne la place pas en `pending`.
- Terminer la liste des résultats par « Offres exclues et pourquoi ». Ne pas numéroter ces annonces avec la sélection ; afficher leur score lorsqu’il existe et tous leurs motifs d’exclusion. Ne pas répéter dans cette section les annonces `pending` déjà affichées à revérifier.
- Afficher en rouge tout prérequis obligatoire non démontré, inconnu ou non satisfait. Un prérequis obligatoire non satisfait force la troisième section, mais le score affiché reste le score de correspondance non pénalisé.
- Terminer le message par une section informative « Sites consultés » provenant de `visited_sources` dans le rapport complet. Elle doit inclure tous les sites visités pendant la recherche, même ceux qui n'ont fourni aucune offre retenue.
- Mettre systématiquement `laurent.sintes74@gmail.com` en copie cachée. La CLI l’utilise par défaut et le fichier `.eml` ainsi que le manifeste doivent contenir cette adresse dans leur champ `Bcc` / `bcc`.
- Ne joindre que le CV PDF validé et généré localement.
- Garder les paquets de communication sous `generated/offer-feedback/` : ils restent locaux, sont ignorés par Git et exclus de GitHub Pages.
- Un message préparé a le statut `draft_prepared`; seul un connecteur de messagerie peut créer ou envoyer un brouillon distant.
