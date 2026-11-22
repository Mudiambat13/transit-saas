# Transit Suivi — application Android (chauffeur / adjoint)

Envoie la position du bus au serveur Transit SaaS, **écran verrouillé**, même avec un réseau intermittent.

> **Statut honnête** : ce code a été vérifié par compilation Kotlin contre les stubs du SDK Android 34, par 15 tests JUnit du cœur (JVM) et par un envoi réel de son JSON vers le serveur Django. **L'APK n'a pas été construit et l'app n'a jamais tourné sur un téléphone** (pas de SDK Android dans l'environnement de développement). Prévoyez un test réel sur vos téléphones avant tout déploiement ; des ajustements mineurs au premier build sont possibles.

## Construire l'APK
1. Installer Android Studio (Koala ou plus récent, JDK 17).
2. `File > Open` → dossier `android/`. Studio télécharge Gradle 8.9 et le SDK 35, puis synchronise.
3. Debug : `Run` sur un téléphone relié en USB (mode développeur) — accepte `http://` (ex. `http://10.0.2.2:8000` depuis l'émulateur).
4. Release : `Build > Generate Signed App Bundle / APK > APK`, créer un keystore **et le sauvegarder** (sans lui, pas de mise à jour). Copier l'APK sur les téléphones (installation hors Play Store : autoriser « sources inconnues »).
5. En ligne de commande (SDK installé) : `gradle wrapper` une fois, puis `./gradlew assembleRelease`, `./gradlew testDebugUnitTest`.

## Utilisation
1. Le serveur doit être en **HTTPS** (release). Dans l'app : adresse du serveur, email et mot de passe du compte chauffeur (rôle DRIVER ou gestionnaire d'agence). Le compte doit être lié à un chauffeur (Flotte > Chauffeurs).
2. Choisir le voyage → **Démarrer le suivi** → accepter localisation et notifications.
3. Appuyer sur « Autoriser l'app à rester active (batterie) ».
4. Verrouiller l'écran. Une notification « Suivi du bus actif » reste affichée. **Arrêter** depuis l'app ou la notification (termine la session côté serveur). Le suivi s'arrête aussi tout seul quand le voyage est terminé/annulé.

## Téléphones à économie d'énergie agressive (Tecno, Infinix, Itel, Xiaomi, Oppo, Samsung…)
Réglages > Applications > Transit Suivi : batterie « Sans restriction », **démarrage automatique** activé, et verrouiller l'app dans la liste des applications récentes (cadenas). Ne pas la « balayer » depuis les récentes. Sur Tecno/Infinix : Gestionnaire de téléphone > Autodémarrage et Protection des applications en arrière-plan. À vérifier sur chaque modèle de flotte.

## Comportement hors réseau
Positions écrites sur disque (jusqu'à ~21 h), envoyées par lots dès que le réseau revient, dans l'ordre. Le serveur ignore les doublons. Notification et écran indiquent « Hors ligne : N position(s) en attente ».

## Structure
- `core/` Kotlin pur et testé : échantillonnage, file `FilePointQueue`, `FlushEngine`.
- `Api.kt` client HTTP ; `TrackingService.kt` service de premier plan ; `MainActivity.kt` écran unique.
- Permissions : localisation, service de premier plan (location), notifications, wake lock, exemption batterie.
