# Madwine: análise focada de Proton e backend gráfico

## Resultado

Foi preparada uma alteração local e reproduzível para o Madwine v0.1.22, conforme autorização do usuário. O AppImage original não foi modificado. O patch redireciona a seleção interna de `GE-Proton11-5-x86_64` para `proton-cachyos-native`, habilita a opção Madwine que reutiliza o Proton instalado e impede o padrão automático de WineD3D no lançamento. O launcher exige uma instalação CachyOS executável e um dispositivo listado pelo `vulkaninfo`.

A alteração está implementada em `prepare-cachyos.py`, `run-cachyos.sh` e `install.sh`; instruções e reversão estão em `README-CACHYOS.md`. O instalador fixa o release v0.1.22, preserva o original em `$XDG_DATA_HOME/madwine/Madwine_0.1.22_amd64.original.AppImage` e instala o AppDir modificado ao lado.

## Identidade dos arquivos

- AppImage original: `Madwine_0.1.22_amd64.AppImage`, 84.400.632 bytes; SHA-256 `f6a05177f186c96dde5b948ed12c16e9ca9e85e703f947be8e267da3a584501b`.
- ELF original `usr/bin/madwine`: 15.683.048 bytes; SHA-256 `8c9079e40659145e9de979601d2d9d740f5c7a157f76d9385b9c64f55215a42b`; Build ID `a255d9c2e840f7d67baf2bdc7503fc6f70cdf0d1`.
- ELF corrigido: SHA-256 `512837169e6b1a16ac454ecb847e08b466d899254fbda7349e6ecd1e581b7be6`.
- Cópia temporária usada para validação no cloud: `/tmp/madwine-cachyos-e2e`. O manifesto reproduzível foi salvo em `.analysis/reports/madwine-cachyos-manifest.json`.

O patcher recusa hashes, tamanhos, cabeçalhos ELF, referências LEA, strings ou instruções diferentes dos bytes analisados. Também recusa sobrescrever um destino existente que não tenha manifesto e hash válidos. A segunda preparação foi chamada com um caminho de `unsquashfs` inexistente e retornou o mesmo hash sem reextrair ou reaplicar o patch, confirmando a reutilização idempotente.

## Mudanças binárias verificadas

1. `GE-Proton11-5-x86_64` tem 20 bytes e é apontada por seis referências conhecidas. O nome compartilhava seu fim com `using the copy from Steam`; esses bytes foram preservados.
2. `proton-cachyos-native` tem 21 bytes e foi gravada na folga de 24 bytes entre `.eh_frame` e `.text`, começando no offset/VMA `0x74bfe8`. As seis LEAs apontam para ela e os seis comprimentos passaram de 20 para 21.
3. O primeiro `PT_LOAD` somente de leitura cresceu de `0x74bfe8` para `0x74bffd`, mantendo três bytes até o próximo segmento em `0x74c000`; `readelf` confirmou que o segmento executável seguinte não mudou.
4. O primeiro candidato `.local/share/Steam/compatibilitytools.d` foi substituído por `/usr/share/steam/compatibilitytools.d`. O caminho novo tem **37 bytes** (o valor preliminar de 36 no rascunho foi corrigido após contagem/validação). O comprimento explícito foi ajustado para 37. A rotina de junção observada descarta o prefixo anterior quando o componente é absoluto.

As verificações finais com `readelf`, `strings` e `objdump` confirmaram o tamanho do segmento, o novo nome e o comprimento `0x25` do caminho absoluto, além das referências apontarem à nova string. O AppImage original manteve seu SHA-256 esperado.

## Configuração e launcher

O launcher exige `/usr/share/steam/compatibilitytools.d/proton-cachyos-native/proton` executável e saída de dispositivo `GPU<n>:` em `vulkaninfo --summary`. Em seguida habilita `reuseSteamProton: true` em `$XDG_CONFIG_HOME/madwine/config.json` (ou `~/.config/madwine/config.json`), mantendo as demais chaves e criando backup timestampado antes de alterar um arquivo existente. JSON inválido interrompe o lançamento.

A desmontagem mostra o carregamento do literal `reuseSteamProton` pelo parser booleano e um byte de configuração que condiciona a chamada da rotina de busca Proton em `VA 0xa8d420`. Isso liga estaticamente a configuração ao fluxo alterado; a função não foi recuperada em pseudocódigo REA.

O processo do Madwine é iniciado com `PROTON_USE_WINED3D=0`; `PROTON_USE_WINED3D11` e um `PROTONPATH` externo são removidos para evitar política ou runtime conflitantes. Essas mudanças são escopadas ao launcher. O binário analisado consulta `PROTON_USE_WINED3D` e só tenta inserir `1` quando a variável está ausente. A desmontagem mostra que Madwine insere `PROTONPATH` no ambiente UMU a partir do caminho escolhido internamente, por isso uma variável externa isolada não resolveria a seleção.

O launcher preserva argumentos e código de saída e não tem fallback silencioso para GE ou WineD3D. Use-o nos atalhos do desktop; iniciar o AppImage original ou outro AppDir ignora a alteração. O patch é exclusivo do v0.1.22 e atualizações futuras precisam de nova análise.

## Testes e limites

- `bash -n install.sh run-cachyos.sh`: passou.
- `python3 -m unittest discover -s tests -v`: 6 testes passaram. Cobriram patch de todas as referências, string compartilhada, rejeição de hash/instrução divergente, recusa de AppImage desconhecido, launcher com diretórios contendo espaços, argumentos e código de saída, backup da configuração, ausência do Proton e ausência de dispositivo Vulkan.
- A preparação completa extraiu o AppImage original e produziu o ELF corrigido descrito acima. O executável não foi iniciado.
- Os testes do launcher usam doubles. Eles verificam o contrato do launcher, mas não provam que Madwine realmente passa o ambiente até UMU/Proton, que o jogo usa DXVK ou que o prefixo é compatível.
- O valor local de `STEAM_COMPAT_CONFIG` e configurações já existentes no prefixo não estão disponíveis no cloud; o launcher controla `PROTON_USE_WINED3D` e remove `PROTON_USE_WINED3D11`, mas a confirmação final do backend deve ser feita na máquina local.
- A máquina cloud não tem `proton-cachyos-native`, `umu-run`, `vulkaninfo` nem dispositivo Vulkan. A verificação de Vulkan real, GPU selecionada, DXVK/HUD e estabilidade precisa ocorrer no computador CachyOS.

## REA/Ghidra

REA 6.7.0 e Ghidra 12.1.4 foram usados pela CLI porque as ferramentas REA MCP não estavam expostas nesta sessão. A análise Ghidra automática não reconheceu a função-alvo em `VA 0xa8d420`/Ghidra `0xb8d420`; por isso a correlação detalhada permanece baseada em desmontagem estática, sem pseudocódigo recuperado para a rotina-alvo. A análise também reportou um PNG embutido inválido. Nenhuma configuração MCP foi alterada.

Evidências REA efetivamente retornadas, com o estado salvo em `.analysis/reports/`:

- `ev_4935cd8c3a75ef5045af77a668dccaaf9817cece816ea4df68afdb308f721793`: busca de procedimentos na região Ghidra `0xb8`.
- `ev_1a2176f4e4c7e7b36f7417d28d559399a7ffdc0d0dfe9e410eeb68f0194329d6`: `FUN_00b8e020`, não é a rotina de busca GE.
- `ev_02e9e25bdbc7320316bb47f122b1b1ba4408865b0b6f5d4c91a09d91ace99d09`: `FUN_00b8b3e0`, também não é a rotina-alvo.

## CPU e memória da máquina cloud

- CPU: Intel Xeon Platinum 8573C; 5 CPUs lógicas visíveis (`0–4`), com cota do contêiner de 4 vCPUs.
- RAM: limite efetivo do contêiner de 32 GiB (`memory.max = 34359738368`).
