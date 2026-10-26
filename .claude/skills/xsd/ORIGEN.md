# De dónde sale esta skill

Esta carpeta es copia **textual** de la skill `xsd` del plugin XSD (XSANDERS
Design Kit), que vive en su propio repositorio. No se edita acá: un cambio
al método, a las herramientas o al informe se hace allá y se vuelve a copiar.
Lo que es de Colm3na (ficha, inventario, sesiones, contexto e historial) sí
vive acá, en `xsd/proyectos/mitrabajo/`.

- Repositorio: https://github.com/snavello/xsanders-design-kit
- Carpeta copiada: `plugins/xsd/skills/xsd/`
- Commit: `f81ccccb8645c9abc1cc30f537c9473cbaf856c6` (2026-10-26)
- Versión del plugin: 1.1.0 (suma el catálogo de estilos)

Se copia en vez de instalar el plugin para que `/xsd` ande en cualquier
sesión de este repositorio, también en la nube, sin depender de llegar a
otro repo. La ventana de avance (plugin `avance-agentes`) no se copia: es
opcional y se instala desde el mismo repositorio.

## Para actualizarla

1. En el repo del kit, `git pull` y anotar el commit.
2. Borrar esta carpeta menos este archivo y copiar `plugins/xsd/skills/xsd/`.
3. Cambiar el commit de arriba y recalcular los SHA-256 de abajo
   (`test_xsd.py` falla si no coinciden).

## SHA-256 de la copia

  - `METODO.md`: `7a3069d002889bc6ddfdf3fb6899170496c25a5278b2d27b0c1a44f74598c7ea`
  - `SKILL.md`: `68b5e53798338570bbdd52c701dd102bcffcc20003d6a31aaa2a21ea7d191d89`
  - `catalogo/LEEME.md`: `6797c07e5793493cb6be940839a8d2ff8356102946999873eb9f8a14f9a33ea1`
  - `catalogo/acme.json`: `aef62399ff4292bfcc0a467e8aa66fcbb8a3b35e13a6a159e1c4fe2aa7b5be8e`
  - `catalogo/armar.py`: `fc9964374de093279d53ef223fb52e55db5ca265f5e63cfa6c16489b446dbe0a`
  - `catalogo/base.css`: `d3b3904e9638463f030378bfb1fe5f8f3f2fe83ae042abe6468bad7551de902b`
  - `catalogo/captura.cjs`: `0c9c07cd147de9aaf760e727029e485ec49bf2cbb480c7e56e39dd94b58f4e44`
  - `catalogo/encargos/estilo.md`: `fc2bb60705019a7e7bc31dec182a105dd1280f6e905e9b0b4ebb4c0bb2426efb`
  - `catalogo/encargos/extraccion.md`: `dee3ac947ec9d6a0d99f23eb48d03e4b7d8c7967f5db05335a8f8b6abf451c06`
  - `catalogo/encargos/movimiento.md`: `43fe2c93051aaced4cb9a6284a0c9131daa07ed715c2819fd82690f47af8e6ec`
  - `catalogo/estilos/aluminio.css`: `68de29977466bd09659c42ea4d1a5121e0f59c7fe25599673dc3f4ed96721919`
  - `catalogo/estilos/aluminio.heroe.html`: `468b4c16e2d60e7830495fb5097dc52c0e9c0cc3182dc72fd2ce04bdf0c24a10`
  - `catalogo/estilos/anden-senaletica.css`: `f1e6ee01989ba7f082fb8b80351ea1b07015f2f9e6befedfd2f809ba0b9ffca2`
  - `catalogo/estilos/anden-senaletica.heroe.html`: `63a25941fff565be9287911576dfcf08766aa04c6d18192f5a489fa909b3e929`
  - `catalogo/estilos/bloque-bauhaus.css`: `907b00b6614cb35e89a2d52d4afcf411f7a9876c615b21503e225724c3f581a8`
  - `catalogo/estilos/bloque-bauhaus.heroe.html`: `8dee5a47c7c0f6a4ee522db8cd5ed8291867e64f1c356e7f0fc3bd1616f3025a`
  - `catalogo/estilos/box-carrera.css`: `034e73ac82d95481c5e4273999c7dba4360f11f0831fffddd1847a910c423e72`
  - `catalogo/estilos/box-carrera.heroe.html`: `d37cace02e02940132b1ae7189c15437c38ae3c6dc25d45884ea83dfa50101ce`
  - `catalogo/estilos/cartelera.css`: `7a17cb990fd87efea6e5171a05626dd0275d208e67d683ec5c47969aed41ad75`
  - `catalogo/estilos/cartelera.heroe.html`: `5663b3a8a9d650c0d27ee17f3cb0c9ba88c105644b926a85f6486578c5018033`
  - `catalogo/estilos/cercano-paneles.css`: `0515be76d5af33feb8c9994a0508d18b92e19968c96df8dcdf62ee1ce1cb2211`
  - `catalogo/estilos/cercano-paneles.heroe.html`: `e1018a1a0646306403ff1f085bbce47cf6df29c595b056cdde89b0fc9dd4fa4d`
  - `catalogo/estilos/chaleco-reflectivo.css`: `ef0e682c06d7824db98204992617c2d7c314c71dedf3794fbda21b7500291912`
  - `catalogo/estilos/chaleco-reflectivo.heroe.html`: `a7ac66cc1b57fba4070d092aeccffd3ae863608ba7a42b055750dbac40da8377`
  - `catalogo/estilos/cine-subtitulo.css`: `1693a8cb8a1bba9b5b55bc2d34852f39b868273da8131ff74c8846951df6b280`
  - `catalogo/estilos/cine-subtitulo.heroe.html`: `e735398bb3408796259ba563b3ca43f9cd6df13e89557de58a5e0f0f1df0e945`
  - `catalogo/estilos/claridad-govuk.css`: `366394f3419eec70f37e644cf8fc9337012ca6f7db50a9c04f3706bb60a91892`
  - `catalogo/estilos/claridad-govuk.heroe.html`: `4840eb4c99619e450e2331ce1759c21d8c28c1fec61457ccd608b46e0d27e6eb`
  - `catalogo/estilos/colmena-sutil.css`: `ba66cd064d09e813875c213d4ea2651a2e7f0ece4b31fef4960d0baa957f7e96`
  - `catalogo/estilos/colmena-sutil.heroe.html`: `26b5c41c7f667ba04a0cf9a54877dff2e7ba1977a4ddff6a8c735612ab0edfde`
  - `catalogo/estilos/contraluz-medido.css`: `1109423ddacb1a697f66a37b419c67f74b5e5d92076b8a670ba79c2a046c7dc1`
  - `catalogo/estilos/contraluz-medido.heroe.html`: `21efd79333ff67eb7e442248df3c91a4c994327ac01c303926afb1a3597f00e3`
  - `catalogo/estilos/credencial-impresion-seguridad.css`: `1f137cfa2dff8489f6050f644a33eadbc05fa51ddbbb7bda33b63e279e02deac`
  - `catalogo/estilos/credencial-impresion-seguridad.heroe.html`: `0a0a0646c5bc3a0bafd2aa10e5b81680f04c47880854fed2353c3c50172a0cf3`
  - `catalogo/estilos/cupertino.css`: `7d10b201f81bceb5bb762cc43719b46f231ac6000ff8fd395708f431144d4f69`
  - `catalogo/estilos/cupertino.heroe.html`: `02bbe097cf3c60e116a33711207ffdf21d372570b78eeb6c49d3b0567dfdf252`
  - `catalogo/estilos/documental-duotono.css`: `6ac1bbcdb553e568bae9fe660fee1bc68a34092660d32ca809a38dd147c79844`
  - `catalogo/estilos/electrico-configurador.css`: `46ba2015a72d4aae5ae11f2e2d969ad7a4920ac58b246da979d42aedba0d7453`
  - `catalogo/estilos/electrico-laguna.css`: `bab15ae0ab46e5fd43e375cbcc9a4a4173a695aa08ae32afc87bf88df5725854`
  - `catalogo/estilos/electrico-sobrio-fluor.css`: `aee98fe5a1c7b60e9b5073f04d0c1a1b3fc6c79c5b6588a6327ba3ee8a6dd8df`
  - `catalogo/estilos/electrico-sobrio-fluor.heroe.html`: `dc28cd2f1d6f752864ef08d01e9f47f59e23057e5a39dd629f010e8ef16bd343`
  - `catalogo/estilos/esfera-relojeria.css`: `ac51df595497089825e561a8da14e2ee0013f78a6e14b4820d682b85dd933f6c`
  - `catalogo/estilos/esfera-relojeria.heroe.html`: `ce218199477e647bd572975d793af06b41824054521998d2cfe43ad7669ddcbc`
  - `catalogo/estilos/espacial-vidrio.css`: `0585251d47c31043321a9d5668c25ec3e2eff956ac23a62f110c5a9b5bc13528`
  - `catalogo/estilos/espacial-vidrio.heroe.html`: `612b713dffd2d3d9fd09ddc6f572ff577ea017facc05e7b1676dab65343b9528`
  - `catalogo/estilos/estadio-led.css`: `7e225bc8e86ce758569923d14f2c8e2d4eefd5f3439aed50ee48492163bb6f6a`
  - `catalogo/estilos/estadio-led.heroe.html`: `8845c60f562acb4efeafdd96feb12906ca62b07d9b43b707459d0eb58e49f469`
  - `catalogo/estilos/expresivo-material.css`: `5acc00cd3a3b0f24161c6dd79a25efab61b0d75a0455ff6f69e8f9e94f24fae4`
  - `catalogo/estilos/expresivo-material.heroe.html`: `162480d64275cbe8bd9642aa83ad9ab55fae6ae8081ea89463e94f97ac6f2285`
  - `catalogo/estilos/fluor-resaltador.css`: `c70fc9d175f72bfd80ffbe9c5bb15ad8f6fccbaf91e4bff96e4deacd402830a2`
  - `catalogo/estilos/fluor-resaltador.heroe.html`: `0fd1feedb8d37c9733add72e355ef35fe3277b2cc3a36345aea6b6652cbf7e44`
  - `catalogo/estilos/funcion-rams.css`: `5be799c83792944f21ff0d79d45a49ed3ebbbfaa0b39bd1bdd7ca287b862c24e`
  - `catalogo/estilos/funcion-rams.heroe.html`: `7c4cc664ac763cd2ea1877a134422a1fa25f97d9dd0cc27f1f60c0316dcd9e9f`
  - `catalogo/estilos/galeria-fotolibro.css`: `e4a6735b1dc394772b30759f328c8b2968b7638063f878aba046d3fc1a7724a6`
  - `catalogo/estilos/galeria-fotolibro.heroe.html`: `6e6c285b4aec1b6c67d54b6deeea84d992594ee87ec1b42842143ac229bf8a29`
  - `catalogo/estilos/grafito-pro.css`: `f80c84ac406123288ad765b4d62f905c7d225b9e57fe322cddf532f7ab92c6fe`
  - `catalogo/estilos/grafito-pro.heroe.html`: `3e457cf620191fef791c043b0adec30200eaaae50dcefec469b5be93c364138e`
  - `catalogo/estilos/hilo.css`: `29c5f7ea488fda4836b9a2d662f4f7bdfbd3df89804ce4b0cbd8f907939fa1e6`
  - `catalogo/estilos/hipercoche.css`: `48ea2f9d81b51d242db890af57eac32d7d8e7845ca79b296dde36fe704005b18`
  - `catalogo/estilos/hipercoche.heroe.html`: `2eaf2b78d98b32b869e4139d59d1423223d71d13180188fb809800d73a949a01`
  - `catalogo/estilos/hoja-de-trabajo-colm3na.css`: `02c020081f8047ba8cb1babfa43c68a77ebf791e97cf6b888da1963dde50b635`
  - `catalogo/estilos/impulso-voltio.css`: `ab9e799a4bd9e6af597b4d22c1e4278210478d98b371dd77952879b34dbaf0e6`
  - `catalogo/estilos/impulso-voltio.heroe.html`: `3ad83e0aa69e1a01d4970d77fcfaca445c9ad1870e1ada1ba5de4df981026cdd`
  - `catalogo/estilos/instructivo.css`: `e9bf530a6eb6b7ee75acee5cf9ebc22f0d6be7ec2e18d22cc075304449c84a4c`
  - `catalogo/estilos/instructivo.heroe.html`: `ad06c069b6bafb90ec8e221c9eeb0f913c435777619f5340c87036597f1b0a7f`
  - `catalogo/estilos/linea-de-tiempo.css`: `50ce2775c67383565f2d85b04c593a8771152c259b691ec0f843f4df4df2f5a7`
  - `catalogo/estilos/linea-de-tiempo.heroe.html`: `143eb5eb6d13b4ace0babdfc9fb81d0850615a621c38ffd42c3ee631ddf426df`
  - `catalogo/estilos/marcador-deportivo.css`: `797440dea6a27a0f319d23a7c673f23d56e5279173db2a8ed744dccd7789e88d`
  - `catalogo/estilos/marcador-deportivo.heroe.html`: `b2b69f88451f04c3789d5a7727393e95d85a7f3758275a25cff271d5d7e22a24`
  - `catalogo/estilos/mosaico-baldosa-calcarea.css`: `39bfe24d5b04aa4d25039b4b3f3e6461718c6b44acd587e0defa009977b94c21`
  - `catalogo/estilos/mosaico-baldosa-calcarea.heroe.html`: `3f8a524d9b196f013eb1caafa23ceb0d7d2f3e69383125fe4c9d41de277afbcd`
  - `catalogo/estilos/movimiento-sereno.css`: `0dad06682c91155518780156a94a034edf133d21aca196863ac634653e33345a`
  - `catalogo/estilos/movimiento-sereno.heroe.html`: `67ec93fa2cab71ad6746acdaa48dff3cb7c7e0be2a1bf759ab206dd8c2c97be8`
  - `catalogo/estilos/nordico-sereno.css`: `7c28b537fad8b0ed2c38be1d1beafd58fd8bcafad01f3c2dff7c53783605ad1e`
  - `catalogo/estilos/nordico-sereno.heroe.html`: `7750f0338aa9443194b5067edb2a3580959c77621be09bc8b4745f4f4d4a40ab`
  - `catalogo/estilos/noticiero-indigo-claro.css`: `5c08e9a6360a4245fa6bcb8d2f2f011b29fe6303c97c5231987b0d3760dd12c7`
  - `catalogo/estilos/noticiero-indigo-claro.heroe.html`: `daa28eb53bdd007a36798c1d7564b7a2789aebde90c57afa50a908c9d16d954d`
  - `catalogo/estilos/noticiero-oscuro-fluor.css`: `50c19a2c47d888d90f499038c37564d5d9241e84584d84a3d7c43698edab1eca`
  - `catalogo/estilos/noticiero-oscuro-fluor.heroe.html`: `f18f2810333fa199cc672e388b1833bd791c87885436279d0e7a14e0286779c2`
  - `catalogo/estilos/nucleo-verde.css`: `6e3436e71792238357f60482707903cb72ec67c39a6af06b341a951f4526c018`
  - `catalogo/estilos/nucleo-verde.heroe.html`: `df3626893150a171d11069570c9bc01051fdc21b7483ae9a13e72bf20ba833bc`
  - `catalogo/estilos/oro-sueco.css`: `27ced8f22adde1629364fb1d53523ea420c55538b1788d4dd325693a3a769a58`
  - `catalogo/estilos/oro-sueco.heroe.html`: `31db72ff699421d5db6e1907f90a394261e5fe0b544e3d98150c6c6fe7ca4d70`
  - `catalogo/estilos/pagos-refinados.css`: `7c92e0bdd4cbe992d0537433896b97c19a600fca6c927cd214b169f70f712f58`
  - `catalogo/estilos/pagos-refinados.heroe.html`: `44e91c6fb2bd9e7304372c38235c1469ebd7a361d924af056da92e927a63a6c3`
  - `catalogo/estilos/pop-color-pleno.css`: `2de833c971a5fa0ef4c906b642ac5a4b4c2daac3cce7718b4c206536ecd36796`
  - `catalogo/estilos/pop-color-pleno.heroe.html`: `2c4105bef412fffdb36701879e68bf9d62d445927287b30176e01c8b6fdba53b`
  - `catalogo/estilos/precision.css`: `041825572a6097f8791ae11337b0b0233ab96b2e79aca8fe0a2667d23c5991bc`
  - `catalogo/estilos/precision.heroe.html`: `4fa2fd45455a0881aa134520a708959756a2d7883933c76eca38e15eaa3dc7b9`
  - `catalogo/estilos/pulso-minimal.css`: `2704cdfe1285d897aa7a8a264668b39b8fc19888a4f419d95415a3bee5093776`
  - `catalogo/estilos/pulso-minimal.heroe.html`: `ec04da0afd090e253916a448dde49afffb48d391296be25c40430824869e3a8e`
  - `catalogo/estilos/punto-rojo.css`: `e38407089fd30190604c0c0c18a578df63fa63aafa011d101044bc5e19ce57c3`
  - `catalogo/estilos/punto-rojo.heroe.html`: `403fa37c21eddc5348e1a00660192db7d8d61a61450ae0a0e4a6980ba0020c7f`
  - `catalogo/estilos/revista-gremio.css`: `1430aa78772188089f04bd2cc2ee923690061c080138d8b379a3a2f3e7c86364`
  - `catalogo/estilos/revista-gremio.heroe.html`: `d270baa3e76f563f2c581e4bc3a37293681b11e0c13f494090df8d1cad93a2bd`
  - `catalogo/estilos/semaforo-lampara.css`: `511f4c87042fc55157cb3f96b876b9312da5a33bea79500e2d6891eaeb911fff`
  - `catalogo/estilos/semaforo-lampara.heroe.html`: `439b8bf3ab760813daa5e0314a16e9232b574bb924b325abae10f08b28b37f3e`
  - `catalogo/estilos/senaletica-suave.css`: `920a40285655e9f60230ba7e9b0fcfcda21fea05c68e7ea990b920e35a6bf9b2`
  - `catalogo/estilos/senaletica-suave.heroe.html`: `aab99b1e37f07c87ee0edcae3b40c13962108be28a6babccff183359a74d972d`
  - `catalogo/estilos/sereno-linea-movil.css`: `22d59d399be471d4324d114e7335be1c4c39e93fa419e9204551af8a7c33170a`
  - `catalogo/estilos/sereno-linea-movil.heroe.html`: `9e1444a03142162026a3b98e3c0cd11b54536e67803d9a4e2a6c309d6d7ac21b`
  - `catalogo/estilos/sintesis-total.css`: `7a601de7b9894ffd1df88c9b9a23500f7d4e305e40a9552244ead15b3738439e`
  - `catalogo/estilos/sintesis-total.heroe.html`: `720645ba61ce800e553488b453f42118faf2b9b75937f6e1fba0424d87827059`
  - `catalogo/estilos/sintetizador.css`: `73b77b4a8da436539bcbb78c0dad16bd94bb77c810eaf502fd08de502d737ee3`
  - `catalogo/estilos/sintetizador.heroe.html`: `c32b33db899120ac4579f5fed5d8f811f66de99e6ac01594ade114e300994f19`
  - `catalogo/estilos/talon-recibo-talonario.css`: `5ed8cbea1803ba338c8a69c0b5eae4d164b3fa7e0b71581eb4b59c423bd4960d`
  - `catalogo/estilos/talon-recibo-talonario.heroe.html`: `9d9ca6cde4cf2b6d932bfb08507c1b41f985a52014257d27bac68b412e787b4d`
  - `catalogo/estilos/tapa-revista-gigante.css`: `a09e51141526e3dd5de2946da436b89511347b78d9dff080d688426f046ac266`
  - `catalogo/estilos/tapa-revista-gigante.heroe.html`: `569717dd06030aa72c013b98edb9065665da3dda40572b1521dff918a1b56316`
  - `catalogo/estilos/telon.css`: `1e3471f4004ab5f318227650a9ebee809dff4c89dbd43259a981c46c7f173508`
  - `catalogo/estilos/telon.heroe.html`: `db802dbfd2f9637509358b2f877fcd99a2df2138b7176726e3a23c2195440691`
  - `catalogo/estilos/tinta-suizo.css`: `f04d7c30e4ff20c2bab749a36c1c90243ad3dee2cbd3a4c62bac3cab23ee08f0`
  - `catalogo/estilos/tonal-primario.css`: `af25a81bf466962eab3198e407ee8d71739f870f9dc10c7a0cfb71d587b872aa`
  - `catalogo/estilos/tonal-primario.heroe.html`: `37d72a2b0427386473b40233b7fcc89ad6dd745c2f02224df9280c017f804dd0`
  - `catalogo/estilos/uboard-informe-editorial.css`: `9a66a460d042b8a21fda6cf9221b4088464f91d8c1d695c8724813072791402d`
  - `catalogo/estilos/uboard-informe-editorial.heroe.html`: `91c591396dc70c906fe491ba54efc6fd0e0eae5523787620772aeb1aa9d595b3`
  - `catalogo/estilos/uboard-planilla.css`: `9d2a1d4af809c355cbf018d39ffdb2aec2238b546b0f56a3d716600c45c22c6a`
  - `catalogo/estilos/vidrio-claro.css`: `ccab71c11ca7b282e37883b448376791a14dc052d6c1c507fae6a947eba38d17`
  - `catalogo/estilos/vidrio-claro.heroe.html`: `80e8a41371922b9467c1247ac13fda94c5467b2f6528f093b889d13ed967055d`
  - `catalogo/estilos/vivo-micromovimiento.css`: `db4c128edce7547c59d814e8f5d57f87f085f22f4aa44b15bda095079c620eea`
  - `catalogo/estilos/vivo-micromovimiento.heroe.html`: `7f88f569b4697e48dce87b0b5eca53c6b031999c6975fca396cb990873209d5a`
  - `catalogo/estilos/zocalo-noticiero.css`: `bd5d00a6c39da09750750a8183e573c6a3abec4b7c69ab086d151cfa76703049`
  - `catalogo/estilos/zocalo-noticiero.heroe.html`: `e63a0cf0b84d8f9df23ad44276bcb351308542d265a4d07e23995085c0e119f8`
  - `catalogo/estilos.json`: `de043f6726816f13a8efa948c958914508b4a66f7c3c1c71836012493274afb8`
  - `catalogo/fotos/acuerdo.jpg`: `75a0aaca7f97e5b82d99ead3f287961b0f6633ce280881ae5b155e367bc3ac5d`
  - `catalogo/fotos/calle.jpg`: `c4d53e756018f6cea984d1646c656ee3dae6b9e8efd02825950f8b05fd732b2c`
  - `catalogo/fotos/creditos.json`: `b2b52fafb211dd1d579a686bc59ba45548fd20d5e06d98b7740f5446953c50ee`
  - `catalogo/fotos/edificio.jpg`: `941053b36bc3d732bc7dc01596970be63b02afc65a5c92cdda774c1bbe31cdab`
  - `catalogo/fotos/equipo.jpg`: `b8c8924ae7e49974098f5706ce51615a8c35bd9294d627fef6a8289e247057b0`
  - `catalogo/fotos/herramientas.jpg`: `0764d334df43eb327fdd19560d73a5b5b6d97f2a53b6187e66627b50a5f4032c`
  - `catalogo/fotos/persona.jpg`: `761b7bfdf4c971d65716f3f21e352c9a4890dadf5ca678532927f0e5f56679b2`
  - `catalogo/fotos/tecnico.jpg`: `9201e4435b910f1a19e6af71c8603813be8f7871de18730b5f201bf622edaf08`
  - `catalogo/molde.html`: `3452d4ffd93787068b21e991bbd96fcaf5a1ec38efb455cdb6c16ac67201b348`
  - `catalogo/pagina.html`: `e4ae4fcdd016f7bc3221f46a742f03fc4a75accca65828bd7b15aa1ec01d52f4`
  - `herramientas/capturar.cjs`: `a7ae0905e43798436baba3214a861ec66597285c49c8a46c28ffd539fd0698fb`
  - `herramientas/xsd.py`: `76dfa291d0049de28f6138d05c931d432a931653f48fc5e7af53cd5d219aca1a`
  - `informe/index.html`: `b2b017acdb11e4302a9de610f0de5e73193344c206e075fede88d075380c388b`
  - `plantillas/brief_equipo.md`: `4847cb4beccce47db0c2fd8ba405e35f7011fda96bbae39de519c46c6ad3af05`
  - `plantillas/brief_revisor.md`: `a9379c09bf5f3e0da55162e98e962d6538a959ff1f01ae02340b37d9000624ca`
  - `plantillas/brief_segunda_vuelta.md`: `e1b144aae579c67e7ffccf99b533f43bea3ea858961f4104e56f798cb7a81c6f`
  - `plantillas/ficha.json`: `ec50834ee554251cabe1c143f4be4e392461434da1a0c77d17a1675096428e75`
