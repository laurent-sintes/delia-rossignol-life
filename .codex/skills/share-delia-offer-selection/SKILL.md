---
name: share-delia-offer-selection
description: Préparer, prévisualiser et faire valider par Délia un message de revue d’une sélection d’offres, avec liens directs, site public et CV PDF joint. Utiliser cette skill lorsqu’il faut partager un classement d’offres avec Délia, demander son avis, créer un brouillon Gmail ou traiter son retour structuré. Ne jamais envoyer un email sans autorisation explicite.
---

# Partage d’une sélection d’offres

Préparer un paquet de brouillon traçable : texte, HTML, fichier `.eml`, manifeste, lien vers le site public et CV PDF joint. Le paquet ne déclenche aucun envoi.

## Workflow

1. Utiliser le dernier rapport complet `generated/offer-search/YYYY-MM-DD-full.json` ou demander à l’utilisateur celui à partager. Partager toutes les offres pertinentes jusqu’à 50, regroupées dans l’ordre `priority`, `possible`, `informational`, puis triées par pertinence décroissante dans chaque section ; ne pas réduire silencieusement à un top 10.
2. Vérifier le CV généré dans `site/assets/downloads/` avec `python scripts/delia_life.py check-documents`.
3. Préparer le brouillon, avec une adresse de destinataire explicitement fournie. Pour une sélection éditoriale, ajouter les identifiants des offres retenues ; le moteur les regroupe ensuite par section et les trie par score :

   ```powershell
   python scripts/delia_life.py prepare-offer-feedback-email generated/offer-search/YYYY-MM-DD-full.json --recipient "adresse-de-delia@example.com" --bcc "laurent.sintes74@gmail.com" --site-url "https://laurent-sintes.github.io/delia-rossignol-life/" --limit 50 --output generated/offer-feedback/YYYY-MM-DD
   ```

4. Ouvrir `offer-selection.txt`, `offer-selection.eml` et `manifest.json`, puis contrôler le destinataire, la copie cachée, les liens, le nombre d’offres et le PDF joint avant toute création de brouillon distant.
5. Pour une modification du classement, des offres ou du message, exécuter `python scripts/repo_flow.py review-operational` : ce contrôle vérifie le code et les données sans régénérer le CV ni reconstruire le site.
6. Si un connecteur de messagerie est disponible, créer un brouillon distant à partir de `offer-selection.eml`. Ne jamais l’envoyer sans une instruction explicite de l’utilisateur.
7. À réception de la réponse de Délia, séparer ses avis sur les offres de tout fait de carrière, puis utiliser le workflow de revue avant de modifier la stratégie de recherche.

## Règles

- Pour chaque offre, afficher un en-tête constant : secteur d’activité, mission / poste, salaire proposé (ou « non communiquée »), pertinence sur 100, puis contrat et lieu. Terminer par le « Point de vigilance » éventuel en orange dans le HTML. Ne jamais inclure de seuil salarial, contrainte familiale ou détail sensible dans le message.
- Afficher les trois sections non vides avec les titres « Il faut répondre, ça matche et tu as des chances d’un retour positif », « Tu peux répondre, on ne sait jamais » et « Je te les mets pour info, mais il y a peu de chances ». Conserver une numérotation globale stable entre les sections.
- Afficher en rouge tout prérequis obligatoire non démontré, inconnu ou non satisfait. Un prérequis obligatoire non satisfait force la troisième section, mais le score affiché reste le score de correspondance non pénalisé.
- Terminer le message par une section informative « Sites consultés » provenant de `visited_sources` dans le rapport complet. Elle doit inclure tous les sites visités pendant la recherche, même ceux qui n'ont fourni aucune offre retenue.
- Mettre systématiquement `laurent.sintes74@gmail.com` en copie cachée. La CLI l’utilise par défaut et le fichier `.eml` ainsi que le manifeste doivent contenir cette adresse dans leur champ `Bcc` / `bcc`.
- Ne joindre que le CV PDF validé et généré localement.
- Garder les paquets de communication sous `generated/offer-feedback/` : ils sont versionnés mais exclus de GitHub Pages.
- Un message préparé a le statut `draft_prepared`; seul un connecteur de messagerie peut créer ou envoyer un brouillon distant.
