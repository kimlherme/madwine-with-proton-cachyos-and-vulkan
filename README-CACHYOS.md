# Madwine v0.1.22 com Proton CachyOS

Este procedimento prepara uma cópia local e fixada do Madwine v0.1.22 para procurar `proton-cachyos-native`. Ele mantém o AppImage original intacto e não altera o Proton instalado no sistema.

## Requisitos

- Python 3, `unsquashfs` (pacote `squashfs-tools`) e `curl` ou `wget`.
- `proton-cachyos-native` executável em `/usr/share/steam/compatibilitytools.d/proton-cachyos-native/proton`.
- `vulkaninfo` (pacote `vulkan-tools`) e um dispositivo Vulkan disponível.

No CachyOS, instale as ferramentas de extração se necessário:

```sh
sudo pacman -S --needed squashfs-tools
```

Na cópia deste repositório que contém `prepare-cachyos.py` e `run-cachyos.sh`, execute:

```sh
./install.sh
```

O instalador baixa somente o AppImage v0.1.22 e confere seu SHA-256 antes da extração. O destino padrão é `$XDG_DATA_HOME/madwine`, ou `~/.local/share/madwine` quando `XDG_DATA_HOME` não está definido. O original fica em `Madwine_0.1.22_amd64.original.AppImage`; o AppDir alterado fica em `Madwine-CachyOS/`.

O instalador termina iniciando `run-cachyos.sh`. O launcher exige Proton CachyOS executável e um dispositivo listado por `vulkaninfo --summary`; em seguida define `PROTON_USE_WINED3D=0` somente para Madwine, remove variáveis herdadas que poderiam conflitar com o runtime e executa o AppDir. Não há fallback para GE nem para WineD3D. Use o caminho impresso pelo instalador nos atalhos do desktop para que eles também passem por essas verificações.

Antes de iniciar Madwine, o launcher ativa `reuseSteamProton: true` em `madwine/config.json` dentro de `$XDG_CONFIG_HOME` (ou `~/.config`). Os demais campos são preservados. Se a configuração mudar, uma cópia é guardada ao lado com o sufixo `.pre-cachyos-<data>.bak`; uma configuração JSON inválida interrompe a inicialização sem sobrescrevê-la.

## Preparar manualmente

O patcher confere o SHA-256 do AppImage, o SHA-256 do executável extraído e cada sequência ELF antes de escrever. Ele só aceita a versão analisada e não remove ou sobrescreve um AppDir de destino desconhecido:

```sh
python3 prepare-cachyos.py \
  --appimage ~/.local/share/madwine/Madwine_0.1.22_amd64.original.AppImage \
  --output ~/.local/share/madwine/Madwine-CachyOS
```

Uma preparação existente só é reutilizada se o manifesto e o hash do executável alterado corresponderem. Para outra versão, os offsets não são reutilizados.

## Conferir e reverter

Confira Vulkan e a GPU antes de iniciar:

```sh
vulkaninfo --summary
```

Para observar DXVK durante um jogo, pode iniciar com:

```sh
DXVK_HUD=devinfo,fps,frametimes,compiler ~/.local/share/madwine/run-cachyos.sh
```

Confirme no processo/logs que o Proton em uso está sob `proton-cachyos-native`; o mock de teste não comprova o comportamento da máquina real. A ausência do HUD, isoladamente, também não prova uso de WineD3D.

Para reverter, feche Madwine e execute o original preservado (ajuste `$XDG_DATA_HOME` se ele estiver definido):

```sh
~/.local/share/madwine/Madwine_0.1.22_amd64.original.AppImage --appimage-extract-and-run
```

Reponha a configuração anterior copiando o backup `.pre-cachyos-*.bak` sobre `$XDG_CONFIG_HOME/madwine/config.json` (ou `~/.config/madwine/config.json`), se quiser desfazer também a opção de reutilização do Proton. O launcher e a configuração só afetam a execução iniciada por ele.

## Limites

O patch foi preparado contra os bytes do v0.1.22 e o launcher foi testado com doubles. A máquina cloud não tem o runtime CachyOS nem hardware Vulkan, portanto o uso real de DXVK/Vulkan, GPU escolhida, estabilidade e compatibilidade do prefixo precisam ser confirmados no computador que tem CachyOS. A atualização automática do aplicativo não foi avaliada; releases futuras exigem análise e patch próprios.
