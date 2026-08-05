# Verified UFW runtime probe — raport Juniorki

## Cel i zakres

Celem sesji było zaimplementowanie bezpiecznego, uprzywilejowanego pomiaru
rzeczywistego stanu runtime UFW dla Bhola Pulse. Zakres obejmował wyłącznie
publiczne repozytorium, kod probe, collector, jednostki systemd, packaging,
testy, dokumentację i walidację artefaktów bez instalowania pakietu.

- Repozytorium: `lbudzynowski/bhola-pulse`
- Gałąź: `agent/verified-ufw-runtime-probe`
- Base SHA: `90d704ef93167da5f0ac49fc77eec08cb086ab59`
- Implementation HEAD przed raportem:
  `00dadaa4e3befcfd1b92012c43123ab2d9d65fbe`
- Wersja funkcjonalna: `0.1.2`
- Wersja binarna Debian: `0.1.2-1`

Nie było otwartego PR w Bhola Pulse dotyczącego UFW lub runtime probe. Raport
diagnostyczny z draft PR `lbudzynowski/bhola-diagnostics#3` wykorzystano tylko
jako potwierdzenie przyczyny: brak uprawnień powodował `unconfirmed`, a stara
logika mapowała go bezpodstawnie na `degraded`.

## Architektura

Przepływ danych ma jedną wąską granicę uprawnień:

```text
systemd root oneshot + CAP_NET_ADMIN
  -> /usr/sbin/nft --json list ruleset
  -> JSON i graf łańcuchów wyłącznie w pamięci
  -> minimalny atomowy JSON pod /run
  -> nieuprzywilejowany collector Bhola Pulse
```

Probe nie przyjmuje argumentów, nie uruchamia shella i wykonuje jedną stałą,
absolutną komendę read-only. Timeout `nft` wynosi 3 sekundy, a jednostki 10
sekund. Stdout rulesetu istnieje tylko w pamięci procesu; stderr jest kierowany
do `/dev/null`. Pełny ruleset nie jest logowany, zapisywany ani zwracany.

Parser buduje graf łańcuchów z JSON nftables. Rozpoznaje ściśle nazwane łańcuchy
UFW, `jump` i `goto`, rzeczywiste base chains oraz hook `input`. `active` wymaga
osiągalnego z hooka input łańcucha UFW zawierającego runtime rules. Pusty
osiągalny łańcuch jest `inactive`; osierocone artefakty lub niespójny graf są
`unconfirmed`. Pusty, uszkodzony lub zbyt duży output jest `error`, nigdy
`inactive`.

## Model zagrożeń

Chronione są przede wszystkim:

- integralność hostowego rulesetu i konfiguracji UFW;
- poufność reguł, adresów, portów, interfejsów, komentarzy i liczników;
- brak ogólnego interfejsu poleceń na granicy root/user;
- integralność pliku stanu czytanego przez zwykłego użytkownika;
- odporność collectora na symlinki, TOCTOU, częściowe zapisy, nieprawidłowe
  prawa, ownera, schemat, typy, enumy i czas;
- zachowanie prawdziwego hostowego network namespace.

Atakujący jako zwykły użytkownik nie może zapisać katalogu ani pliku runtime.
Collector nie ufa samej ścieżce: wykonuje `lstat()` rodzica i pliku, odrzuca
symlink, plik innego typu, dodatkowy hardlink, group/world-write, niewłaściwego
ownera i rozmiar poza limitem. Następnie otwiera z `O_NOFOLLOW`, porównuje
`fstat()` z wcześniejszym inode i czyta maksymalnie 4097 bajtów.

Root pozostaje poza modelem pełnej ochrony: root może zmienić jednostkę, probe,
ruleset albo zaufany plik. Mechanizm minimalizuje uprawnienia procesu i ekspozycję
danych, ale nie broni hosta przed już przejętym rootem.

## Granica uprawnień

Tylko `bhola-pulse-ufw-probe.service` działa jako root. Jego
`CapabilityBoundingSet` zawiera wyłącznie `CAP_NET_ADMIN`; ambient capabilities
są puste. Dashboard, launcher, provider, Python i binarka `nft` nie dostają
capabilities, setuid, Polkit ani reguł sudoers.

Nie ma D-Bus, socketu, API ani argumentu użytkownika. `PrivateNetwork=yes` jest
celowo nieobecne, ponieważ probe musi widzieć network namespace hosta. Jednostka
ogranicza address families do `AF_UNIX AF_NETLINK` i blokuje adresy IP.

Lokalny systemd to `255.4-1ubuntu8.16`; wszystkie użyte dyrektywy są obsługiwane
przez tę wersję. Offline `systemd-analyze security` zwrócił exposure `1.4 OK`.
Jedyny celowo zaakceptowany punkt dotyczący `UMask=0022` wynika z wymagania, aby
zwykły dashboard mógł czytać minimalny plik 0644.

## Pliki i jednostki

Najważniejsze pliki:

- `src/bhola_ufw_probe.py` — probe, parser i atomowy writer;
- `src/bhola_services.py` — zaufany reader i mapowanie collectora;
- `packaging/systemd/bhola-pulse-ufw-probe.service`;
- `packaging/systemd/bhola-pulse-ufw-probe.timer`;
- `tests/fixtures/ufw/` i `tests/test_ufw_probe.py`;
- `tests/test_services.py`;
- `tests/test_systemd_packaging.py`;
- `docs/ufw-runtime-probe.md`;
- `scripts/build-deb.sh` i `debian/build-pr-source`;
- `.github/workflows/ci.yml` i `.github/workflows/source-package.yml`.

Service ma `Type=oneshot`, `RuntimeDirectory=bhola-pulse`, mode 0755,
`RuntimeDirectoryPreserve=yes` i jedyny write allow-list
`/run/bhola-pulse`. Timer wykonuje pierwszy pomiar po 15–20 sekundach i następne
co około 45–50 sekund. systemd nie uruchamia równoległej instancji aktywnego
oneshotu. Nie ma zależności od sieci, catch-up ani pętli retry.

Hardening obejmuje między innymi `NoNewPrivileges`, `ProtectSystem=strict`,
ochronę home, devices, kernel tunables/modules/logs, control groups, clock i
hostname, `MemoryDenyWriteExecute`, `RestrictSUIDSGID`, `RestrictRealtime`,
`RestrictNamespaces`, `ProtectProc=invisible`, `ProcSubset=pid`, native syscall
architecture oraz deny-list niepotrzebnych klas syscalli.

## Schemat pliku runtime

Ścieżka: `/run/bhola-pulse/ufw-status.json`.

```json
{
  "schema_version": 1,
  "observed_at_epoch": 0,
  "config": "enabled",
  "runtime": "active",
  "verified": true,
  "source": "nftables",
  "detail": "verified_runtime_active"
}
```

Maksymalny rozmiar to 4096 bajtów. Wszystkie wartości tekstowe mają zamknięte
enumy. Pole `detail` jest uzasadnionym rozszerzeniem potrzebnym do rozróżnienia
zweryfikowanego dowodu od timeoutu, błędu komendy, parsera lub niespójności.

Writer tworzy plik tymczasowy w tym samym katalogu, ustawia 0644, zapisuje,
flushuje, wykonuje `fsync()`, atomowo zastępuje cel przez `os.replace()` i
wykonuje `fsync()` katalogu. Katalog i plik nie są zapisywalne przez group/other.

JSON nie zawiera rulesetu, stdout, stderr, adresu, portu, interfejsu, komentarza,
licznika, hostname, użytkownika, machine ID, sekretu ani ścieżki domowej.

## Mapowanie statusów

Próg świeżości wynosi 120 sekund, a tolerancja czasu z przyszłości 5 sekund.

| Dowód | Status | Confidence | Detail |
| --- | --- | --- | --- |
| konfiguracja disabled | `off` | high | `config_disabled` |
| enabled + świeży verified active | `ok` | high | `verified_runtime_active` |
| enabled + świeży verified inactive | `degraded` | high | `verified_runtime_inactive` |
| brak pliku | `unknown` | low | `probe_missing` |
| stary plik | `unknown` | low | `probe_stale` |
| niebezpieczny lub błędny plik | `unknown` | low | `probe_invalid` |
| timeout lub błąd probe | `unknown` | low | `probe_error` |
| osierocony lub niespójny runtime | `unknown` | low | `probe_unconfirmed` |

Najważniejsza regresja jest jawnie pokryta testem: `permission denied` nie
oznacza `degraded`. Checkout developerski bez systemowego probe bezpiecznie
pokazuje `unknown` i nie próbuje uruchamiać `nft` jako użytkownik.

## Testy

Pełny `scripts/check.sh` zakończył się powodzeniem:

- privacy-check;
- compileall kodu i testów;
- 116 unittestów;
- provider self-check;
- shell syntax.

Fixture-based testy probe obejmują active, inactive, pusty podpięty łańcuch UFW,
osierocone łańcuchy, hook bez UFW, niespójny graf, malformed i empty JSON,
timeout, nonzero exit, oversized output, brak programu, zapis atomowy, cleanup
pliku tymczasowego i minimalny prywatny JSON.

Testy collectora obejmują świeże active/inactive, config disabled, missing,
stale, symlink, non-regular, group/world-write, oversized, owner/parent,
schema, enumy, przyszły timestamp, częściowy zapis, probe error i brak
bezpodstawnego `degraded`.

Testy systemd i packaging obejmują semantykę dyrektyw, jedyną capability,
hostowy namespace, timer, isolated-root `systemd-analyze verify`, ścieżki
payloadu, prawa i zakazane mechanizmy.

## Wyniki walidacji

- `bash scripts/check.sh`: PASS, 116 testów.
- `python3 -m unittest discover -s tests -v`: PASS, 116 testów.
- `python3 scripts/privacy-check.py`: PASS, 68 śledzonych plików przed raportem.
- `git diff --check`: PASS.
- isolated-root `systemd-analyze verify`: PASS.
- offline `systemd-analyze security`: PASS, exposure `1.4 OK`.
- statyczny scan privilege/nft mutation/full-output logging: PASS.
- binary package `0.1.2-1`: zbudowany i sprawdzony bez instalacji.
- unsigned PR source package Noble: build, extract i binary rebuild PASS.
- unsigned PR source package Resolute: build, extract i binary rebuild PASS.
- każdy source rebuild ponownie wykonał 116 testów: PASS.
- source/binary metadata scan na prywatne home path i lokalny username: PASS.
- orig tar ownership i modes: znormalizowane do `root/root`, 0644/0755.
- debhelper lifecycle: postinst enable/start, prerm stop, postrm purge stanu
  timera — PASS.
- GitHub CI: do uruchomienia po pushu; wynik należy odnotować w draft PR.

Debhelper nie był instalowany na hoście. Do lokalnej walidacji pobrano publiczne
pakiety `.deb` do katalogu tymczasowego i rozpakowano je bez rejestracji w dpkg.

## Packaging i wersja

`nftables` zmieniono z `Recommends` na `Depends`, ponieważ obowiązkowy systemowy
probe nie może działać bez `/usr/sbin/nft`. `iputils-ping` pozostaje
`Recommends`. Nie dodano ręcznych maintainer scripts; lifecycle jednostek
generuje debhelper 13 przez `dh_installsystemd`.

`VERSION` i upstream mają `0.1.2`, a changelog Debian `0.1.2-1`. Bezpośredni
builder release generuje `bhola-pulse_0.1.2-1_all.deb` i `SHA256SUMS`.

Fail-closed builder PPA pozostaje przypięty do zweryfikowanego immutable SHA
wydania 0.1.1 i prawidłowo odrzuca payload 0.1.2. Osobny
`debian/build-pr-source` tworzy tylko niepodpisane artefakty `~pr1~` do CI.
Nie zmieniono pinu na branch ani ruchomy ref.

## Ryzyka i ograniczenia

- Parser potwierdza strukturalne podpięcie i obecność reguł UFW, ale nie próbuje
  udowadniać pełnej semantyki każdej reguły ani skuteczności polityki dla
  konkretnego pakietu.
- Probe wymaga `CAP_NET_ADMIN`, bo kernel wymaga go do odczytu rzeczywistego
  rulesetu. Ryzyko jest ograniczone krótkim procesem, stałą komendą, bounding
  setem i sandboxem.
- Wynik może być ważny do 120 sekund. To jawny kompromis między odpornością na
  opóźnienie timera a świeżością.
- `RuntimeDirectoryPreserve=yes` zachowuje wynik po końcu oneshotu. Plik jest
  ulotny i znika po restarcie hosta, lecz może pozostać po stopie jednostki;
  collector odrzuci go po 120 sekundach.
- Jednostki nie były instalowane ani uruchamiane przez systemd hosta. Pełna
  runtime walidacja capability i hostowego netlink pozostaje krokiem po
  instalacji podpisanego pakietu.
- Merge zmiany wersji do `main` może uruchomić istniejący workflow GitHub
  Release. Ten draft PR nie może być scalony, dopóki release nie zostanie
  świadomie zatwierdzony.

## Plan późniejszego wdrożenia

1. Poczekać na zielone CI i zakończyć review draft PR.
2. Przed merge świadomie zatwierdzić release 0.1.2 i osobno zaktualizować pin PPA
   dopiero do zweryfikowanego immutable commita/tagu.
3. Zbudować, podpisać i opublikować zgodnie z polityką projektu; zweryfikować
   tag, checksum i payload.
4. Zapisać aktualnie zainstalowaną wersję i zachować zweryfikowany pakiet 0.1.1.
5. Zainstalować 0.1.2-1 przez APT.
6. Sprawdzić timer, service, `CapabilityBoundingSet`, `NoNewPrivileges`, brak
   `PrivateNetwork`, `systemd-analyze verify` i `systemd-analyze security`.
7. Poczekać na dwa interwały, sprawdzić wyłącznie minimalny plik stanu i jego
   owner/mode/size, a następnie `bhola-pulse --check`.
8. Nie zmieniać reguł UFW/nftables w ramach wdrożenia.

## Rollback

Rollback polega na instalacji wcześniej zweryfikowanego pakietu 0.1.1 przez
APT. Wygenerowane przez debhelper skrypty 0.1.2 zatrzymają i wyłączą timer przy
downgrade/removal. Potem należy wykonać `daemon-reload` jeśli APT go nie wykonał,
potwierdzić brak aktywnego timera oraz uruchomić `bhola-pulse --check`.

Stary collector ignoruje ewentualny plik pod `/run`; plik jest ulotny i znika po
reboocie. Pełne usunięcie zapewnia `apt purge bhola-pulse`. Rollback nie może
zmieniać UFW ani nftables policy.

## Rzeczy niewykonane

- nie zainstalowano pakietu;
- nie skopiowano jednostek do systemowego katalogu;
- nie wykonano `systemctl enable`, `start`, `restart` ani `daemon-reload`;
- nie wykonano uprzywilejowanego `nft list ruleset`;
- nie odczytano ani nie opublikowano rzeczywistego rulesetu hosta;
- nie zmieniono UFW, nftables, systemd, usług ani konfiguracji hosta;
- nie utworzono tagu ani GitHub Release;
- nie podpisano ani nie wysłano source package;
- nie wykonano `dput` ani publikacji PPA;
- nie scalono PR i nie oznaczono go jako ready.

## Potwierdzenie bezpieczeństwa sesji

Sesja zmieniła wyłącznie pliki nowego checkoutu repozytorium oraz ignorowane
lokalne artefakty build/test. Nie instalowano paczek i nie zmieniono stanu
systemowego Bholi, UFW, nftables ani systemd. Nie utworzono tagu, release ani
publikacji PPA.
