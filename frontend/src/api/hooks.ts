import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from './client';
import type { CascadeRequest } from './types';
export const useCatalog = () => useQuery({ queryKey: ['catalog'], queryFn: ({ signal }) => api.catalog(signal), staleTime: Infinity, gcTime: Infinity, retry: 1 });
export const useCatalogMeta = () => useQuery({ queryKey: ['catalog-meta'], queryFn: ({ signal }) => api.catalogMeta(signal), staleTime: 60000, retry: 1 });
export const useConjunctions = () => useQuery({ queryKey: ['conjunctions'], queryFn: ({ signal }) => api.conjunctions(signal), staleTime: 60000, retry: 1 });
export const useConjunction = (id: string | undefined) => useQuery({ queryKey: ['conjunction', id], queryFn: ({ signal }) => api.conjunction(id ?? '', signal), enabled: Boolean(id), staleTime: 60000, retry: 1 });
export const useCascade = () => useMutation({ mutationFn: (request: CascadeRequest) => api.cascade(request) });
