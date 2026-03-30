import { create } from "zustand";
import type { Brand, Channel, Product } from "@/types";

export interface LogoInfo {
  url: string;
  label: string;
  filename?: string;
}

export interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  [key: string]: unknown;
}

interface BrandState {
  // Data
  brand: Brand | null;
  channels: Record<string, ChannelConfig>;
  products: Product[];
  logos: LogoInfo[];
  activeChannels: Channel[];

  // Loading flags
  loading: boolean;
  saving: boolean;
  loadingProducts: boolean;
  savingChannels: boolean;
  uploadingLogo: boolean;

  // Actions
  setBrand: (brand: Brand | null) => void;
  setChannels: (channels: Record<string, ChannelConfig>) => void;
  setProducts: (products: Product[]) => void;
  setLogos: (logos: LogoInfo[]) => void;
  setActiveChannels: (channels: Channel[]) => void;
  setLoading: (loading: boolean) => void;
  setSaving: (saving: boolean) => void;
  setLoadingProducts: (loading: boolean) => void;
  setSavingChannels: (saving: boolean) => void;
  setUploadingLogo: (uploading: boolean) => void;
  reset: () => void;
}

const initialState = {
  brand: null,
  channels: {} as Record<string, ChannelConfig>,
  products: [] as Product[],
  logos: [] as LogoInfo[],
  activeChannels: [] as Channel[],
  loading: true,
  saving: false,
  loadingProducts: false,
  savingChannels: false,
  uploadingLogo: false,
};

export const useBrandStore = create<BrandState>()((set) => ({
  ...initialState,

  setBrand: (brand) => set({ brand }),
  setChannels: (channels) => set({ channels }),
  setProducts: (products) => set({ products }),
  setLogos: (logos) => set({ logos }),
  setActiveChannels: (activeChannels) => set({ activeChannels }),
  setLoading: (loading) => set({ loading }),
  setSaving: (saving) => set({ saving }),
  setLoadingProducts: (loadingProducts) => set({ loadingProducts }),
  setSavingChannels: (savingChannels) => set({ savingChannels }),
  setUploadingLogo: (uploadingLogo) => set({ uploadingLogo }),
  reset: () => set(initialState),
}));
