# Passafile Locale

Server **one-click** per condividere file tra i dispositivi della tua rete locale (Wi-Fi di casa/ufficio), con **QR code** per aprirlo subito dal telefono.

- **Zero dipendenze**: serve solo Python 3.8+ (niente `pip install`)
- **Un solo file**: `pasafile.py`
- **QR code** stampato nel terminale
- Seleziona o trascina i file dal browser, da PC o da telefono
- Download diretto ed elimina file
- Funziona con PC, Mac, Linux, Android e iPhone (browser qualsiasi)

## Avvio one-click

### Windows
Doppio clic su **`start.bat`**.

### macOS / Linux
Doppio clic su **`start.sh`**, oppure in terminale:

```bash
./start.sh
```

### In alternativa (qualsiasi sistema)
```bash
python3 pasafile.py
```

All'avvio il server stampa nel terminale l'indirizzo web e un **QR code**: inquadralo con la fotocamera del telefono per aprire il pannello.

## Uso

1. Avvia il server sul computer collegato alla rete Wi-Fi.
2. Inquadra il QR code col telefono (stessa rete) **oppure** apri l'indirizzo mostrato nel browser.
3. Trascina o seleziona i file nel riquadro **Carica**: appariranno sul PC e sugli altri dispositivi.
4. Da un altro dispositivo, apri l'indirizzo per **scaricare** i file condivisi.

I file caricati finiscono nella cartella `condivisi/` (creata automaticamente accanto allo script).

## Opzioni

| Opzione | Descrizione |
|---|---|
| `-d, --dir CARTELLA` | Cartella da condividere (default: `./condivisi`) |
| `-p, --port PORTA` | Porta del server (default: `8000`, se è occupata prova la successiva) |
| `--open` | Apre automaticamente il browser |

Esempio: condividere una cartella dedicata sulla porta 9000 e aprire il browser:

```bash
python3 pasafile.py -d /percorso/verso/i/tuoi/file -p 9000 --open
```

## API semplice

- `GET /f/nomefile.txt` → download diretto di un file
- `POST /upload` → caricamento multipart (`campo: file`)
- `POST /delete` → elimina un file (`body: name=nomefile.txt`)
- `GET /ping` → `ok` (utile per testare la connessione)

I file vengono condivisi in cartella piatta (i percorsi nelle cartelle secondarie vengono appiattiti).

## Sicurezza

Passafile è pensato per **rette locali fidate** (casa, ufficio):

- il server non è progettato per essere esposto su Internet;
- i percorsi dei file sono validati (niente traversals fuori dalla cartella condivisa);
- le cartelle che iniziano per `.` non vengono mostrate né servite dalla lista.

Se la tua rete non è fidata, non avviare il server.

## Requisiti

- Python 3.8 o superiore (testato anche su 3.13)
- Nessun pacchetto esterno

## Licenza

MIT — vedi [LICENSE](LICENSE).
