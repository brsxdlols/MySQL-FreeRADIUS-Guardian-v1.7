# Proveniencia do modulo

FreeRADIUS 3.0.17, rlm_sqlippool, GPL version 2 ou posterior conforme cabecalho preservado. Fontes modificadas completas do modulo em sqlippool-source.c; header SQL usado em sqlippool-rlm_sql.h; alteracao em sqlippool-null-handle.patch; licenca em SQLIPPOOL-LICENSE.txt.

Backport upstream: https://github.com/FreeRADIUS/freeradius-server/commit/7ac18787d574334cd62150138a8b4aff5de582ef . Fonte base: tag release_3_0_17 do mesmo repositorio. Arquivo de fonte base usado no laboratorio, SHA256: b97b447f4dcdf59c235ba6c44b4e8f3fb7da643b2375cd8d84d16fcb9c62fa90. Dependencias de desenvolvimento: libfreeradius-dev 3.0.17+dfsg-1.1+deb10u1, libtalloc-dev 2.1.14-2, libpcre3-dev 8.39-12, libssl-dev 1.1.1n-0+deb10u3; ambiente Debian buster amd64. A instalacao NAO compila nem baixa essas dependencias.

Procedimento de build usado: fonte 3.0.17 com configuracao autoconf/build headers preparada para o ambiente; copiar headers de /usr/include/freeradius para src/include quando ausentes, incluindo features.h. Include alias include/freeradius-devel aponta para src/include. Compilar o modulo com:

```
gcc -shared -fPIC -O2 -Wall -DNDEBUG -D_GNU_SOURCE -D_REENTRANT -DIS_MODULE=1 \
  -Iinclude -Ideps/usr/include -Ideps/usr/include/x86_64-linux-gnu \
  -Isrc/modules/rlm_sql -include src/include/autoconf.h \
  -include src/include/build.h src/modules/rlm_sqlippool/rlm_sqlippool.c \
  -o rlm_sqlippool-candidate.so
```

O binario distribuido e validado por SHA256 03b654562cd34cbc51381a8e435c51676d41a33f1e2acb24b837b9d32a2d4fba; nao presumir reproducao byte a byte com outro compilador/ambiente. A compatibilidade automatica e restrita aos hashes/pacotes revisados.
