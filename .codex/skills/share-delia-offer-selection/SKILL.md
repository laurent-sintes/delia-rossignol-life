---
name: share-delia-offer-selection
description: Préparer, prévisualiser et faire valider par Délia un message de revue d’une sélection d’offres, avec liens directs, site public et CV PDF joint. Utiliser cette skill lorsqu’il faut partager un classement d’offres avec Délia, demander son avis, créer un brouillon Gmail ou traiter son retour structuré. Ne jamais envoyer un email sans autorisation explicite.
---

# Partage d’une sélection d’offres

Préparer un paquet de brouillon traçable : texte, HTML, fichier `.eml`, manifeste, lien vers le site public et CV PDF joint. Le paquet ne déclenche aucun envoi.

## Workflow

1. Utiliser le dernier rapport `generated/offer-search/YYYY-MM-DD.json` ou demander à l’utilisateur celui à partager.
2. Vérifier le CV généré dans `site/assets/downloads/` avec `python scripts/delia_life.py check-documents`.
3. Préparer le brouillon, avec une adresse de destinataire explicitement fournie. Pour une sélection éditoriale, ajouter les identifiants d’offres dans l’ordre retenu :

   ```powershell
   python scripts/delia_life.py prepare-offer-feedback-email generated/offer-search/YYYY-MM-DD-full.json --recipient "adresse-de-delia@example.com" --site-url "https://laurent-sintes.github.io/delia-rossignol-life/" --offer-id "offre-1" --offer-id "offre-2" --output generated/offer-feedback/YYYY-MM-DD
   ```

4. Ouvrir `offer-selection.txt` et contrôler le destinataire, les liens, le nombre d’offres et le PDF joint avant toute création de brouillon distant.
5. Si un connecteur de messagerie est disponible, créer un brouillon distant à partir de `offer-selection.eml`. Ne jamais l’envoyer sans une instruction explicite de l’utilisateur.
6. À réception de la réponse de Délia, séparer ses avis sur les offres de tout fait de carrière, puis utiliser le workflow de revue avant de modifier la stratégie de recherche.

## Règles

- Ne jamais inclure de seuil salarial, contrainte familiale, détail sensible ou score interne dans le message.
- Ne joindre que le CV PDF validé et généré localement.
- Garder les paquets de communication sous `generated/offer-feedback/` : ils sont versionnés mais exclus de GitHub Pages.
- Un message préparé a le statut `draft_prepared`; seul un connecteur de messagerie peut créer ou envoyer un brouillon distant.
