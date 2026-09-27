<template>
  <n-config-provider :theme="currentTheme">
    <n-message-provider>
      <n-dialog-provider>
        <template v-if="route.name === 'Login'">
          <router-view />
        </template>
        <template v-else>
          <app-layout />
        </template>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { NConfigProvider, NMessageProvider, NDialogProvider, darkTheme } from 'naive-ui';
import { useThemeStore } from '@/stores/theme';
import AppLayout from '@/components/AppLayout.vue';

const route = useRoute();
const themeStore = useThemeStore();

const currentTheme = computed(() => (themeStore.isDark ? darkTheme : null));
</script>

<style>
body {
  margin: 0;
  padding: 0;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  -webkit-font-smoothing: antialiased;
}
</style>
