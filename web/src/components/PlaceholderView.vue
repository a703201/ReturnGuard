<script setup lang="ts">
/** 通用空壳视图：后续批次逐页接入真实功能。 */
import AppIcon from './AppIcon.vue'
import { t } from '../i18n'
const props = defineProps<{ navKey: string; icon: string }>()
</script>

<template>
  <section>
    <h1 class="page-h1">{{ t(`nav.${props.navKey}`) }}</h1>
    <div class="card empty-state" style="margin-top:24px">
      <AppIcon :name="props.icon" :size="44" />
      <h3>{{ t('empty.title') }}</h3>
      <p>{{ t('empty.desc') }}</p>
    </div>
  </section>
</template>

<style scoped>
.page-h1 { font-size: var(--fs-h1); font-weight: 700; letter-spacing: var(--tr-heading); }
</style>
