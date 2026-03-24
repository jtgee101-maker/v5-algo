import { create } from 'zustand';

export const useAppStore = create((set) => ({
  selectedSymbol: 'USOIL',
  autoScan: false,
  sidebarOpen: true,
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setSelectedSymbol: (selectedSymbol) => set({ selectedSymbol }),
  setAutoScan: (autoScan) => set({ autoScan }),
}));
