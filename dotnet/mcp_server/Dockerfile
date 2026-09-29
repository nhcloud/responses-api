FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY PolicyMcpServer.csproj .
RUN dotnet restore
COPY Program.cs PolicyTools.cs appsettings.json ./
RUN dotnet publish -c Release --no-restore -o /out

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
ENV MCP_HOST=0.0.0.0 PORT=8000 DOTNET_ENVIRONMENT=Production
COPY --from=build /out .
USER $APP_UID
EXPOSE 8000
ENTRYPOINT ["dotnet", "PolicyMcpServer.dll"]